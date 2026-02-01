import asyncio
import logging
import json
from aiohttp import web
import aiohttp_cors

from bot.loader import bot, dp
from bot.handlers import router as main_router
from bot.utils import get_all_subjects
from database import (
    init_db, get_user_stats, get_or_create_user, get_user_rank,
    get_ranking_by_period, get_exchange_rate, create_withdrawal,
    get_group_rating, get_admin_dashboard_stats, search_questions,
    delete_question, add_question, get_pending_withdrawals, update_withdrawal_status,
    set_exchange_rate, get_custom_subjects_list, add_custom_subject, remove_custom_subject
)
from bot.config import ADMIN_IDS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- WEB HANDLERS ---
async def handle_index(request):
    return web.FileResponse('./web/index.html')

async def handle_admin(request):
    return web.FileResponse('./web/admin.html')

def get_user_id_from_header(request):
    uid = request.headers.get("X-User-ID")
    if not uid or not uid.isdigit():
        return None
    return int(uid)

def is_admin(request):
    uid = get_user_id_from_header(request)
    if not uid: return False
    return str(uid) in ADMIN_IDS

# --- CLIENT API ---
async def api_user_stats(request):
    uid = get_user_id_from_header(request)
    if not uid:
        return web.json_response({"error": "Unauthorized"}, status=401)
    
    row = await get_or_create_user(uid) 
    if not row:
         return web.json_response({"error": "User not found"}, status=404)
    
    stats = await get_user_stats(uid)
    rank = await get_user_rank(uid)
    
    name = row[2]
    if row[3]: name += f" {row[3]}"
    
    data = {
        "user": {
            "id": row[0],
            "name": name,
            "username": row[1],
            "score": row[4],
            "coins": row[5]
        },
        "stats": stats,
        "rank": rank
    }
    return web.json_response(data)

async def api_rankings(request):
    period = request.query.get("period", "all")
    rows = await get_ranking_by_period(period, limit=20)
    
    results = []
    for r in rows:
        name = r[2] or f"User {r[0]}"
        if r[1]: name = f"@{r[1]}"
        
        results.append({
            "name": name,
            "score": r[3]
        })
    return web.json_response(results)

async def api_exchange_info(request):
    rate = await get_exchange_rate()
    return web.json_response({"rate": rate})

async def api_exchange_request(request):
    uid = get_user_id_from_header(request)
    if not uid:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    try:
        body = await request.json()
        amount = int(body.get("amount", 0))
    except:
        return web.json_response({"error": "Invalid body"}, status=400)
    
    if amount <= 0:
        return web.json_response({"error": "Invalid amount"}, status=400)
        
    rate = await get_exchange_rate()
    money = amount / rate
    
    success, msg = await create_withdrawal(uid, amount, money)
    
    if success:
        # Notify admins
        for admin_id in ADMIN_IDS:
             try:
                 await bot.send_message(admin_id, f"🔔 <b>WebApp Exchange Request!</b>\nUser ID: {uid}\nCoins: {amount}\nMoney: {money:.2f}", parse_mode="HTML")
             except:
                 pass
        return web.json_response({"success": True})
    else:
        return web.json_response({"success": False, "error": msg})

# --- ADMIN API ---
async def api_admin_stats(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    stats = await get_admin_dashboard_stats()
    return web.json_response(stats)

async def api_admin_subjects(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    
    if request.method == 'GET':
        subjects = await get_custom_subjects_list()
        return web.json_response(subjects)
    
    if request.method == 'POST':
        data = await request.json()
        name = data.get('name', '').strip().lower()
        if name:
            await add_custom_subject(name)
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "Invalid or exists"})
        
    if request.method == 'DELETE':
        name = request.query.get('name')
        if name:
            await remove_custom_subject(name)
        return web.json_response({"success": True})

async def api_admin_add_question(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    data = await request.json()
    
    try:
        await add_question(
            subject=data['subject'],
            question=data['question'],
            options=data['options'],
            correct_option_id=data['correct_option'], # 0-3
            created_by=get_user_id_from_header(request)
        )
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"Error adding question: {e}")
        return web.json_response({"success": False, "error": str(e)})

async def api_admin_bulk_txt(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    data = await request.json()
    subject = data.get('subject')
    text = data.get('text', '')
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    added = 0
    errors = 0
    
    for line in lines:
        # Format: Question | v1, v2, v3, v4 | answer (1-4)
        try:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 3: raise ValueError("Invalid format")
            
            q_text = parts[0]
            opts = [o.strip() for o in parts[1].split(',')]
            
            # Answer can be index 1-4 or the text itself? Protocol says 1-4.
            # If user provides text, we might want to match. But let's assume index for simplicity as per admin.py
            ans_raw = parts[2]
            if ans_raw.isdigit():
                correct = int(ans_raw) - 1
            else:
                # Try to find index
                correct = -1
                # TODO: advanced matching if needed
                
            if len(opts) != 4 or not (0 <= correct <= 3):
                raise ValueError("Options or answer invalid")
                
            await add_question(subject, q_text, opts, correct, get_user_id_from_header(request))
            added += 1
        except:
            errors += 1
            
    return web.json_response({"added": added, "errors": errors})

async def api_admin_bulk_pairs(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    data = await request.json()
    
    subject = data.get('subject')
    q_content = data.get('questions', '').strip() # format: 1. Question\na) opt\n...
    a_content = data.get('answers', '').strip() # format: 1. a\n2. b...
    
    # This requires parsing "Question followed by options".
    # Regex approach for standard format
    
    # Simple parser: Split by double newlines or numbered list
    # Let's try a robust line-by-line parser
    
    import re
    
    # Parse Answers first: "1. a", "2. b"
    answers_map = {}
    for line in a_content.split('\n'):
        line = line.strip()
        if not line: continue
        # Match "1. a" or "1 a" or "1) a"
        m = re.match(r'^(\d+)[\.\)]\s*([a-dA-D])', line)
        if m:
            idx = int(m.group(1))
            char = m.group(2).lower()
            ans_idx = ord(char) - ord('a') # 0-3
            answers_map[idx] = ans_idx
            
    # Parse Questions
    # We expect blocks.
    # Logic: Look for "1. ", "2. " start of lines.
    
    blocks = re.split(r'\n(?=\d+[\.\)])', '\n' + q_content)
    # The first element might be empty or header
    
    added = 0
    errors = 0
    
    for block in blocks:
        if not block.strip(): continue
        
        # Extract ID
        m = re.match(r'\n?(\d+)[\.\)]\s*(.*)', block, re.DOTALL)
        if not m: continue
        
        q_num = int(m.group(1))
        rest = m.group(2)
        
        # Extract options: look for a), b), or A), B)
        # Split by options
        # Regex for options: \n[a-d]\) 
        opt_parts = re.split(r'\n[a-dA-D][\)\.]\s*', rest)
        
        if len(opt_parts) < 5: 
            # Maybe format is different? user said:
            # 1. Savol
            # a) variant...
            # This split should work if newlines are present.
            errors += 1
            continue
            
        q_text = opt_parts[0].strip()
        opts = [o.strip() for o in opt_parts[1:5]] # take 4
        
        correct = answers_map.get(q_num)
        
        if correct is not None and len(opts) == 4:
            try:
                await add_question(subject, q_text, opts, correct, get_user_id_from_header(request))
                added += 1
            except:
                errors += 1
        else:
            errors += 1
            
    return web.json_response({"added": added, "errors": errors})

async def api_admin_search(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    
    q = request.query.get('q', '')
    subj = request.query.get('subject')
    
    # Try to parse 'q' as ID if it's digit
    qid = int(q) if q.isdigit() else None
    
    rows = await search_questions(text=q, subject=subj if subj else None, question_id=qid)
    
    res = []
    for r in rows:
        # id, subject, question, op1...op4, correct
        res.append({
            "id": r[0],
            "subject": r[1],
            "question": r[2],
            "options": [r[3], r[4], r[5], r[6]],
            "correct_option_id": r[7]
        })
    return web.json_response(res)

async def api_admin_delete_question(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    qid = request.query.get('id')
    if qid and qid.isdigit():
        await delete_question(int(qid))
        return web.json_response({"success": True})
    return web.json_response({"error": "Invalid ID"})

async def api_admin_withdrawals(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    rows = await get_pending_withdrawals()
    res = []
    for r in rows:
        # id, user_id, username, coins, money, date
        res.append({
            "id": r[0],
            "user_id": r[1],
            "username": r[2],
            "amount_coins": r[3],
            "amount_money": r[4],
            "created_at": r[5]
        })
    return web.json_response(res)

async def api_admin_withdrawal_decision(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    data = await request.json()
    wid = data.get('id')
    status = data.get('status') # approved/rejected
    
    if status not in ['approved', 'rejected']:
        return web.json_response({"error": "Invalid status"})
        
    await update_withdrawal_status(wid, status)
    return web.json_response({"success": True})

async def api_admin_rate(request):
    if not is_admin(request): return web.json_response({"error": "Forbidden"}, status=403)
    
    if request.method == 'POST':
        data = await request.json()
        try:
            rate = float(data.get('rate'))
            await set_exchange_rate(rate)
            return web.json_response({"success": True})
        except:
            return web.json_response({"error": "Invalid rate"})
            
    # GET
    rate = await get_exchange_rate()
    return web.json_response({"rate": rate})


# --- APP SETUP ---
async def on_startup(app):
    await init_db()
    
    # Try init questions
    try:
        from init_questions import init_questions
        await init_questions()
    except Exception:
        pass
        
    dp.include_router(main_router)
    
    # Start bot polling in background
    asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot polling started in background.")

async def main():
    app = web.Application()
    
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    
    # Routes
    app.router.add_get('/', handle_index)
    app.router.add_get('/admin', handle_admin)  # NEW ADMIN ROUTE
    app.router.add_static('/web/', path='./web', name='web')
    
    # API Client
    app.router.add_get('/api/user/stats', api_user_stats)
    app.router.add_get('/api/rankings', api_rankings)
    app.router.add_get('/api/exchange/info', api_exchange_info)
    app.router.add_post('/api/exchange/request', api_exchange_request)
    
    # API Admin
    app.router.add_get('/api/admin/stats', api_admin_stats)
    app.router.add_get('/api/admin/subjects', api_admin_subjects)
    app.router.add_post('/api/admin/subjects', api_admin_subjects)
    app.router.add_delete('/api/admin/subjects', api_admin_subjects)
    
    app.router.add_post('/api/admin/questions/add', api_admin_add_question)
    app.router.add_post('/api/admin/questions/bulk_txt', api_admin_bulk_txt)
    app.router.add_post('/api/admin/questions/bulk_pairs', api_admin_bulk_pairs)
    app.router.add_get('/api/admin/questions/search', api_admin_search)
    app.router.add_delete('/api/admin/questions/delete', api_admin_delete_question)
    
    app.router.add_get('/api/admin/withdrawals', api_admin_withdrawals)
    app.router.add_post('/api/admin/withdrawals/decision', api_admin_withdrawal_decision)
    
    app.router.add_get('/api/admin/rate', api_admin_rate)
    app.router.add_post('/api/admin/rate', api_admin_rate)
    
    for route in list(app.router.routes()):
        cors.add(route)
    
    app.on_startup.append(on_startup)
    
    logger.info("Starting Web Server on port 8080...")
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    web.run_app(main(), port=port)

