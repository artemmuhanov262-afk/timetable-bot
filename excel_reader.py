import pandas as pd
import re
from datetime import datetime
import os

# Конфигурация по умолчанию (если нет config.py)
try:
    from config import EXCEL_FILE_PATH as CONFIG_FILE_PATH, START_DATE
    EXCEL_FILE_PATH = CONFIG_FILE_PATH
except ImportError:
    EXCEL_FILE_PATH = "Расписание.xls"
    START_DATE = "2026-02-02"

DAYS_RU = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']

DAYS_MAP = {
    'ПОНЕДЕЛЬНИК': 'Понедельник',
    'ВТОРНИК': 'Вторник',
    'СРЕДА': 'Среда',
    'ЧЕТВЕРГ': 'Четверг',
    'ПЯТНИЦА': 'Пятница',
    'СУББОТА': 'Суббота',
}

PAIR_TIMES = {
    1: ("08:30", "10:00"),
    2: ("10:10", "11:40"),
    3: ("12:20", "13:50"),
    4: ("14:00", "15:30"),
    5: ("15:40", "17:10"),
    6: ("17:20", "18:50"),
    7: ("19:00", "20:30"),
    8: ("20:40", "22:10"),
}

_timetable_cache = None
_current_file_path = None

def get_course_from_group(group_name):
    match = re.search(r'Б(\d{2})', group_name)
    if match:
        num = int(match.group(1))
        if num == 25:
            return 1
        elif num == 24:
            return 2
        elif num == 23:
            return 3
        elif num == 22:
            return 4
    return None

def get_week_type_name(week_type):
    return "над чертой" if week_type == 1 else "под чертой"

def get_pair_time(pair_num):
    if pair_num in PAIR_TIMES:
        return PAIR_TIMES[pair_num]
    return ("--:--", "--:--")

def find_schedule_file():
    """Автоматически находит файл расписания"""
    global EXCEL_FILE_PATH, _current_file_path
    
    if _current_file_path and os.path.exists(_current_file_path):
        return _current_file_path
    
    if os.path.exists(EXCEL_FILE_PATH):
        _current_file_path = EXCEL_FILE_PATH
        return _current_file_path
    
    alternatives = [
        "Расписание.xlsx",
        "Расписание.xls", 
        "Расписание1.xlsx",
        "Расписание1.xls",
        "schedule.xlsx",
        "schedule.xls"
    ]
    
    for alt in alternatives:
        if os.path.exists(alt):
            _current_file_path = alt
            EXCEL_FILE_PATH = alt
            print(f"✅ Найден файл: {alt}")
            return _current_file_path
    
    print("❌ Файл расписания не найден!")
    return None

def find_groups_on_sheet(df_values):
    """Находит все группы на листе и их колонки"""
    groups = {}
    
    for row_idx in range(min(10, len(df_values))):
        row = df_values[row_idx]
        if not row:
            continue
        for col_idx, cell in enumerate(row):
            if cell and isinstance(cell, str):
                cell_clean = str(cell).strip().upper()
                if re.match(r'^[БМ]\d{2}-\d{3}-\d', cell_clean):
                    if len(cell_clean) <= 15:
                        groups[cell_clean] = {
                            'col': col_idx,
                            'row': row_idx
                        }
                        print(f"     🎓 Найдена группа: {cell_clean} (колонка {col_idx})")
    
    return groups

def parse_timetable_from_sheet(sheet_name, sheet_df):
    """Парсит расписание из одного листа - ОБЪЕДИНЕННАЯ ВЕРСИЯ"""
    data = sheet_df.values.tolist()
    groups = find_groups_on_sheet(data)
    
    if not groups:
        print(f"  ⚠️ На листе {sheet_name} не найдено групп")
        return {}
    
    sheet_timetable = {group_name: {1: {}, 2: {}} for group_name in groups.keys()}
    
    current_day = None
    current_pair = None
    
    for row_idx, row in enumerate(data):
        if not row or len(row) < 5:
            continue
        
        # ========== 1. ОПРЕДЕЛЕНИЕ ДНЯ НЕДЕЛИ ==========
        first_cell = str(row[0]) if row[0] and pd.notna(row[0]) else ""
        first_cell_clean = first_cell.strip().upper()
        
        if first_cell_clean in DAYS_MAP:
            current_day = DAYS_MAP[first_cell_clean]
            print(f"     📅 День: {current_day}")
            
            # ВАЖНО: Проверяем, есть ли в этой же строке данные о паре
            # (некоторые расписания хранят 1 пару в той же строке, что и день)
            pair_cell = row[1] if len(row) > 1 else None
            if pair_cell and pd.notna(pair_cell):
                try:
                    pair_num = int(float(pair_cell))
                    current_pair = pair_num
                    print(f"       Пара {current_pair} (в строке с днем)")
                    # Продолжаем обработку этой же строки как пары
                except:
                    pass
            else:
                current_pair = None
                continue  # Если нет пары в этой строке, переходим к следующей
        
        if not current_day:
            continue
        
        # ========== 2. ОПРЕДЕЛЕНИЕ НОМЕРА ПАРЫ ==========
        pair_cell = row[1] if len(row) > 1 else None
        pair_num = None
        
        if pair_cell and pd.notna(pair_cell):
            try:
                pair_num = int(float(pair_cell))
                if pair_num != current_pair:
                    current_pair = pair_num
                    print(f"       Пара {current_pair} (из колонки B)")
            except (ValueError, TypeError):
                pair_str = str(pair_cell).strip()
                match = re.search(r'(\d+)', pair_str)
                if match:
                    pair_num = int(match.group(1))
                    if pair_num != current_pair:
                        current_pair = pair_num
                        print(f"       Пара {current_pair} (из текста: {pair_str})")
        
        # Если номер пары не найден, но есть предмет - возможно это продолжение предыдущей пары
        if current_pair is None:
            # Проверяем, есть ли предмет в любой из групп
            has_subject = False
            for group_name, group_info in groups.items():
                group_col = group_info['col']
                if group_col in [5, 4]:
                    subject_col = 5
                elif group_col in [10, 9]:
                    subject_col = 10
                else:
                    subject_col = group_col + 1
                
                if subject_col < len(row) and row[subject_col] and pd.notna(row[subject_col]):
                    subject = str(row[subject_col]).strip()
                    if subject and subject.lower() not in ['nan', 'none', '', ' ', '-']:
                        has_subject = True
                        break
            
            if has_subject:
                # Есть предмет, но нет номера - это строка с другой неделей той же пары
                # Используем предыдущий номер пары (current_pair уже установлен)
                pass
            else:
                # Нет ни номера, ни предмета - пропускаем
                continue
        
        # Если всё еще нет номера пары - пропускаем
        if current_pair is None:
            continue
        
        # ========== 3. ОПРЕДЕЛЕНИЕ ТИПА НЕДЕЛИ (ОБЪЕДИНЕННАЯ ВЕРСИЯ) ==========
        week_cell = row[4] if len(row) > 4 else None
        week_types_to_parse = []
        
        if week_cell and pd.notna(week_cell):
            # Преобразуем в строку и убираем лишние пробелы
            week_val = str(week_cell).strip().upper()
            # Убираем возможные скрытые символы
            week_val = re.sub(r'[^\w/]', '', week_val)
            
            print(f"         🔍 Определение недели: '{week_val}' (сырое: '{week_cell}')")
            
            if week_val == 'I' or week_val == '1':
                week_types_to_parse = [1]
                print(f"         ✅ НАД ЧЕРТОЙ (I)")
            elif week_val == 'II' or week_val == '2':
                week_types_to_parse = [2]
                print(f"         ✅ ПОД ЧЕРТОЙ (II)")
            elif week_val in ['I/II', 'I-II', 'I-II', '12', '1/2', 'I-II', 'I II']:
                week_types_to_parse = [1, 2]
                print(f"         ✅ ОБЕ НЕДЕЛИ")
            else:
                # Если не распознали - проверяем по первой букве
                if week_val.startswith('I'):
                    week_types_to_parse = [1]
                    print(f"         ✅ НАД ЧЕРТОЙ (по первой букве I)")
                elif week_val.startswith('II') or week_val.startswith('2'):
                    week_types_to_parse = [2]
                    print(f"         ✅ ПОД ЧЕРТОЙ (по первой букве II)")
                else:
                    week_types_to_parse = [1, 2]
                    print(f"         ⚠️ Не распознано: '{week_val}', добавлено в обе недели")
        else:
            # Если нет данных о неделе, добавляем в обе
            week_types_to_parse = [1, 2]
            print(f"         ⚠️ Нет данных о неделе, добавлено в обе")
        
        # ========== 4. ПАРСИНГ ДАННЫХ ДЛЯ КАЖДОЙ ГРУППЫ ==========
        for group_name, group_info in groups.items():
            group_col = group_info['col']
            
            # Определяем колонки для данных
            if group_col in [5, 4]:
                subject_col = 5
                lesson_type_col = 6
                teacher_col = 7
                room_col = 8
            elif group_col in [10, 9]:
                subject_col = 10
                lesson_type_col = 11
                teacher_col = 12
                room_col = 13
            else:
                subject_col = group_col + 1
                lesson_type_col = group_col + 2
                teacher_col = group_col + 3
                room_col = group_col + 4
            
            # Получаем данные
            subject = ""
            if subject_col < len(row) and row[subject_col] and pd.notna(row[subject_col]):
                subject = str(row[subject_col]).strip()
                subject = re.sub(r'\n+', ' ', subject)
                subject = re.sub(r'\s+', ' ', subject).strip()
                if subject.lower() in ['nan', 'none', '', ' ', '-']:
                    subject = ""
            
            if not subject:
                continue
            
            # Тип занятия
            lesson_type = ""
            if lesson_type_col < len(row) and row[lesson_type_col] and pd.notna(row[lesson_type_col]):
                lesson_type = str(row[lesson_type_col]).strip()
                if lesson_type not in ['nan', 'None']:
                    lesson_type = re.sub(r'\s+', ' ', lesson_type)
                    lesson_type = f" ({lesson_type})"
                else:
                    lesson_type = ""
            
            # Преподаватель
            teacher = ""
            if teacher_col < len(row) and row[teacher_col] and pd.notna(row[teacher_col]):
                teacher = str(row[teacher_col]).strip()
                teacher = re.sub(r'\n+', ' ', teacher)
                teacher = re.sub(r'\s+', ' ', teacher).strip()
                if '  ' in teacher:
                    parts = teacher.split('  ')
                    teacher = parts[0]
                if teacher.lower() in ['nan', 'none']:
                    teacher = ""
            
            # Аудитория
            room = ""
            if room_col < len(row) and row[room_col] and pd.notna(row[room_col]):
                room = str(row[room_col]).strip()
                if room.lower() in ['nan', 'none']:
                    room = ""
            
            full_subject = f"{subject}{lesson_type}"
            
            # Сохраняем для каждого типа недели
            for week_type in week_types_to_parse:
                if current_day not in sheet_timetable[group_name][week_type]:
                    sheet_timetable[group_name][week_type][current_day] = {}
                
                if current_pair not in sheet_timetable[group_name][week_type][current_day]:
                    sheet_timetable[group_name][week_type][current_day][current_pair] = {
                        'subject': full_subject,
                        'teacher': teacher,
                        'room': room,
                        'pair_num': current_pair
                    }
                    week_name = "НАД ЧЕРТОЙ" if week_type == 1 else "ПОД ЧЕРТОЙ"
                    print(f"         ✅ СОХРАНЕНО [{week_name}] {current_pair}: {full_subject[:40]}")
    
    return sheet_timetable
def load_timetable(file_path=None):
    global _timetable_cache, _current_file_path, EXCEL_FILE_PATH
    
    if _timetable_cache is not None:
        return _timetable_cache
    
    if file_path:
        target_file = file_path
    else:
        target_file = find_schedule_file()
    
    if not target_file:
        print("❌ Файл расписания не найден!")
        return {}
    
    _current_file_path = target_file
    EXCEL_FILE_PATH = target_file
    
    print("📖 Загружаем расписание...")
    print(f"📁 Файл: {target_file}")
    
    try:
        if target_file.endswith('.xls'):
            engine = 'xlrd'
        else:
            engine = 'openpyxl'
        
        excel_file = pd.ExcelFile(target_file, engine=engine)
        all_timetable = {}
        
        for sheet_name in excel_file.sheet_names:
            print(f"\n  📄 Лист: {sheet_name}")
            sheet_df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None, engine=engine)
            print(f"     Размер: {len(sheet_df)} строк x {len(sheet_df.columns)} колонок")
            
            sheet_timetable = parse_timetable_from_sheet(sheet_name, sheet_df)
            
            for group_name, group_data in sheet_timetable.items():
                if group_name not in all_timetable:
                    all_timetable[group_name] = {1: {}, 2: {}}
                
                for week_type in [1, 2]:
                    for day, lessons in group_data[week_type].items():
                        if day not in all_timetable[group_name][week_type]:
                            all_timetable[group_name][week_type][day] = {}
                        all_timetable[group_name][week_type][day].update(lessons)
        
        _timetable_cache = all_timetable
        
        total_lessons = 0
        for group in all_timetable:
            for week in all_timetable[group]:
                for day in all_timetable[group][week]:
                    total_lessons += len(all_timetable[group][week][day])
        
        print(f"\n{'='*50}")
        print(f"✅ ЗАГРУЖЕНО: {len(all_timetable)} групп, {total_lessons} занятий")
        print(f"{'='*50}")
        
        if len(all_timetable) > 0:
            print("\n📋 Группы:")
            for group in sorted(all_timetable.keys()):
                course = get_course_from_group(group)
                print(f"   • {group} ({course} курс)" if course else f"   • {group}")
        
        return all_timetable
        
    except Exception as e:
        print(f"❌ Ошибка при загрузке: {e}")
        import traceback
        traceback.print_exc()
        return {}

def get_timetable(group_name, week_type, day_of_week):
    """Возвращает расписание для группы на определенный день"""
    timetable = load_timetable()
    
    if group_name not in timetable:
        return None
    
    if week_type not in timetable[group_name]:
        return []
    
    day_name = DAYS_RU[day_of_week]
    
    all_pairs = []
    
    for pair_num in range(1, 8):
        if day_name in timetable[group_name][week_type] and pair_num in timetable[group_name][week_type][day_name]:
            data = timetable[group_name][week_type][day_name][pair_num]
            all_pairs.append({
                'pair_num': pair_num,
                'subject': data['subject'],
                'teacher': data['teacher'],
                'room': data['room'],
                'start_time': PAIR_TIMES[pair_num][0],
                'end_time': PAIR_TIMES[pair_num][1]
            })
        else:
            all_pairs.append({
                'pair_num': pair_num,
                'subject': "Нет пары",
                'teacher': "",
                'room': "",
                'start_time': PAIR_TIMES[pair_num][0],
                'end_time': PAIR_TIMES[pair_num][1]
            })
    
    return all_pairs

def get_week_schedule(group_name, week_type):
    """
    Возвращает расписание группы на всю неделю для указанного типа недели
    
    Args:
        group_name: название группы
        week_type: 1 - над чертой (I), 2 - под чертой (II)
    
    Returns:
        dict: {день: {пара: {subject, teacher, room}}}
    """
    timetable = load_timetable()
    
    if group_name not in timetable:
        return None
    
    if week_type not in timetable[group_name]:
        return {}
    
    return timetable[group_name][week_type]

def get_all_groups():
    timetable = load_timetable()
    return sorted(timetable.keys())

def get_week_type():
    try:
        start_date = datetime.strptime(START_DATE, "%Y-%m-%d").date()
        today = datetime.now().date()
        delta_days = (today - start_date).days
        if delta_days < 0:
            return 1
        week_number = delta_days // 7
        return 1 if week_number % 2 == 0 else 2
    except:
        return 1

def reload_timetable():
    global _timetable_cache
    _timetable_cache = None
    return load_timetable()

def debug_group_schedule(group_name):
    timetable = load_timetable()
    if group_name not in timetable:
        print(f"❌ Группа {group_name} не найдена")
        return
    
    print(f"\n📋 РАСПИСАНИЕ ДЛЯ {group_name}:")
    for week_type in [1, 2]:
        week_str = "НАД ЧЕРТОЙ" if week_type == 1 else "ПОД ЧЕРТОЙ"
        print(f"\n{'='*50}")
        print(f"{week_str} НЕДЕЛЯ:")
        print(f"{'='*50}")
        
        if week_type not in timetable[group_name]:
            print("  Нет данных")
            continue
        
        for day in DAYS_RU[:5]:
            print(f"\n  📅 {day}:")
            
            for pair_num in range(1, 8):
                start_time, end_time = get_pair_time(pair_num)
                
                if day in timetable[group_name][week_type] and pair_num in timetable[group_name][week_type][day]:
                    data = timetable[group_name][week_type][day][pair_num]
                    print(f"    {pair_num}. {start_time}-{end_time}")
                    print(f"       📚 {data['subject']}")
                    if data['teacher']:
                        print(f"       👨‍🏫 {data['teacher']}")
                    if data['room']:
                        print(f"       📍 {data['room']}")
                    print()
                else:
                    print(f"    {pair_num}. {start_time}-{end_time}")
                    print(f"       📭 Нет пары")
                    print()

if __name__ == "__main__":
    print("="*50)
    print("🤖 ТЕСТИРОВАНИЕ ПАРСЕРА РАСПИСАНИЯ")
    print("="*50)
    
    timetable = load_timetable()
    groups = get_all_groups()
    
    print(f"\n📋 Найдено групп: {len(groups)}")
    print(f"Группы: {groups}")
    
    if groups:
        debug_group_schedule(groups[0])