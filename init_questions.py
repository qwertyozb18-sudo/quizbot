import asyncio
from database import add_question, get_questions_count

INITIAL_QUESTIONS = {
    "english": [
        ("What is the capital of England?", ["London", "Paris", "Berlin", "Madrid"], 0),
        ("How do you say 'Salom' in English?", ["Goodbye", "Hello", "Thanks", "Sorry"], 1),
        ("What color is the sky?", ["Green", "Red", "Blue", "Yellow"], 2),
        ("How many days in a week?", ["5", "6", "7", "8"], 2),
        ("What is 'uy' in English?", ["car", "house", "tree", "book"], 1),
        ("Which is a fruit?", ["Carrot", "Apple", "Potato", "Onion"], 1),
        ("What comes after Monday?", ["Sunday", "Tuesday", "Wednesday", "Friday"], 1),
        ("How many fingers on one hand?", ["3", "4", "5", "6"], 2),
        ("What is 'kitob' in English?", ["pen", "pencil", "book", "paper"], 2),
        ("Which animal can fly?", ["Dog", "Cat", "Bird", "Fish"], 2),
        ("What is 'qizil' in English?", ["blue", "green", "red", "yellow"], 2),
        ("How many months in a year?", ["10", "11", "12", "13"], 2),
        ("What is 'katta' in English?", ["small", "big", "old", "new"], 1),
        ("Which is a vehicle?", ["Chair", "Table", "Car", "Book"], 2),
        ("What is 'yaxshi' in English?", ["bad", "good", "ugly", "sad"], 1),
        ("How many hours in a day?", ["12", "20", "24", "30"], 2),
        ("What is 'eski' in English?", ["new", "big", "old", "small"], 2),
        ("Which season is cold?", ["Summer", "Spring", "Autumn", "Winter"], 3),
        ("What is 'suv' in English?", ["milk", "juice", "water", "tea"], 2),
        ("How many sides in a triangle?", ["2", "3", "4", "5"], 1),
    ],
    "russian": [
        ("Столица России?", ["Москва", "Париж", "Лондон", "Берлин"], 0),
        ("Как будет 'Salom' по-русски?", ["До свидания", "Привет", "Спасибо", "Извините"], 1),
        ("Сколько дней в неделе?", ["5", "6", "7", "8"], 2),
        ("Какого цвета небо?", ["Зелёное", "Красное", "Синее", "Жёлтое"], 2),
        ("Что такое 'uy' по-русски?", ["машина", "дом", "дерево", "книга"], 1),
        ("Какой фрукт?", ["Морковь", "Яблоко", "Картофель", "Лук"], 1),
        ("Что после понедельника?", ["Воскресенье", "Вторник", "Среда", "Пятница"], 1),
        ("Сколько пальцев на руке?", ["3", "4", "5", "6"], 2),
        ("Что такое 'kitob'?", ["ручка", "карандаш", "книга", "бумага"], 2),
        ("Какое животное летает?", ["Собака", "Кошка", "Птица", "Рыба"], 2),
        ("Какого цвета 'qizil'?", ["синий", "зелёный", "красный", "жёлтый"], 2),
        ("Месяцев в году?", ["10", "11", "12", "13"], 2),
        ("'katta' по-русски?", ["маленький", "большой", "старый", "новый"], 1),
        ("Что это транспорт?", ["Стул", "Стол", "Машина", "Книга"], 2),
        ("'yaxshi' по-русски?", ["плохой", "хороший", "уродливый", "грустный"], 1),
        ("Часов в сутках?", ["12", "20", "24", "30"], 2),
        ("'eski' по-русски?", ["новый", "большой", "старый", "маленький"], 2),
        ("Холодное время года?", ["Лето", "Весна", "Осень", "Зима"], 3),
        ("'suv' по-русски?", ["молоко", "сок", "вода", "чай"], 2),
        ("Сторон у треугольника?", ["2", "3", "4", "5"], 1),
    ],
    "math": [
        ("2 + 2 = ?", ["2", "3", "4", "5"], 2),
        ("10 - 5 = ?", ["3", "4", "5", "6"], 2),
        ("3 × 3 = ?", ["6", "7", "8", "9"], 3),
        ("20 ÷ 4 = ?", ["4", "5", "6", "7"], 1),
        ("5 + 7 = ?", ["10", "11", "12", "13"], 2),
        ("15 - 8 = ?", ["5", "6", "7", "8"], 2),
        ("4 × 5 = ?", ["15", "20", "25", "30"], 1),
        ("18 ÷ 3 = ?", ["4", "5", "6", "7"], 2),
        ("9 + 6 = ?", ["13", "14", "15", "16"], 2),
        ("25 - 10 = ?", ["10", "15", "20", "25"], 1),
        ("6 × 7 = ?", ["36", "40", "42", "48"], 2),
        ("30 ÷ 5 = ?", ["5", "6", "7", "8"], 1),
        ("12 + 8 = ?", ["18", "19", "20", "21"], 2),
        ("50 - 15 = ?", ["30", "35", "40", "45"], 1),
        ("8 × 9 = ?", ["64", "72", "80", "81"], 1),
        ("40 ÷ 8 = ?", ["4", "5", "6", "7"], 1),
        ("7 + 13 = ?", ["18", "19", "20", "21"], 2),
        ("100 - 45 = ?", ["50", "55", "60", "65"], 1),
        ("11 × 3 = ?", ["30", "31", "32", "33"], 3),
        ("36 ÷ 6 = ?", ["5", "6", "7", "8"], 1),
    ],
    "physics": [
        ("Yorug'lik tezligi qancha?", ["100,000 km/s", "200,000 km/s", "300,000 km/s", "400,000 km/s"], 2),
        ("Yer atrofida aylanadigan sayyora?", ["Mars", "Quyosh", "Oy", "Venera"], 2),
        ("Suv qaysi haroratda qaynaydi?", ["50°C", "75°C", "100°C", "125°C"], 2),
        ("Gravitatsiya qonunini kim kashf etgan?", ["Einstein", "Newton", "Galileo", "Tesla"], 1),
        ("Energiya birligi nima?", ["Volt", "Amper", "Joule", "Watt"], 2),
        ("Tovush tezligi havoda qancha?", ["240 m/s", "280 m/s", "330 m/s", "380 m/s"], 2),
        ("Elektr toki birligi?", ["Volt", "Amper", "Watt", "Ohm"], 1),
        ("Massa birligi?", ["Newton", "Joule", "Kilogram", "Meter"], 2),
        ("Kuch birligi?", ["Newton", "Joule", "Kilogram", "Watt"], 0),
        ("Quvvat birligi?", ["Newton", "Joule", "Kilogram", "Watt"], 3),
        ("Zaryad birligi?", ["Coulomb", "Amper", "Volt", "Ohm"], 0),
        ("Qarshilik birligi?", ["Volt", "Amper", "Watt", "Ohm"], 3),
        ("Tezlanish birligi?", ["m/s", "m/s²", "m²/s", "s/m"], 1),
        ("Bosim birligi?", ["Newton", "Pascal", "Joule", "Watt"], 1),
        ("Chastota birligi?", ["Hertz", "Watt", "Volt", "Amper"], 0),
        ("Issiqlik birligi?", ["Joule", "Watt", "Kelvin", "Celsius"], 0),
        ("Kuchlanish birligi?", ["Volt", "Amper", "Watt", "Ohm"], 0),
        ("Tezlik birligi?", ["m", "m/s", "m/s²", "s"], 1),
        ("Vaqt birligi?", ["metr", "kilogram", "sekund", "Newton"], 2),
        ("Masofa birligi?", ["metr", "sekund", "kilogram", "Newton"], 0),
    ]
}

async def init_questions():
    """Boshlang'ich savollarni qo'shish"""
    for subject, questions in INITIAL_QUESTIONS.items():
        count = await get_questions_count(subject)
        if count == 0:
            print(f"{subject.capitalize()} fani uchun savollar qo'shilmoqda...")
            for q_text, options, correct_id in questions:
                await add_question(subject, q_text, options, correct_id)
            print(f"{subject.capitalize()}: {len(questions)} ta savol qo'shildi ✓")
        else:
            print(f"{subject.capitalize()}: {count} ta savol allaqachon mavjud")

if __name__ == "__main__":
    asyncio.run(init_questions())
