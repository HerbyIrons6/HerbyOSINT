import json
import subprocess

C2PA_SOURCE_LABELS = {
    'trainedAlgorithmicMedia': '🤖 AI-генерация (trainedAlgorithmicMedia)',
    'compositeSynthetic':      '🔀 Синтетический композит',
    'algorithmicMedia':        '⚙️ Алгоритмический медиа',
    'digitalCapture':          '📷 Оригинальная цифровая съёмка',
    'minorHumanEdits':         '✏️ Редактирование человеком',
}


def execute_check(filepath: str, report_name: str, original_name: str = "") -> bool:
    result = subprocess.run(
        ["exiftool", "-j", filepath],
        capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=15
    )
    if not result.stdout:
        return False

    meta = json.loads(result.stdout)[0]

    # Подменяем техническое имя на оригинальное
    if original_name:
        meta['SourceFile'] = original_name
        meta['FileName']   = original_name

    with open(report_name, "w", encoding="utf-8") as f:
        f.write("╔══════════════════════════════╗\n")
        f.write("║       ПОЛНЫЙ ОТЧЁТ           ║\n")
        f.write("╚══════════════════════════════╝\n\n")
        for key, value in meta.items():
            f.write(f"{key}: {value}\n")
    return True


def execute_check_short(filepath: str, report_name: str, original_name: str = "") -> bool:
    result = subprocess.run(
        ["exiftool", "-j", filepath],
        capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=15
    )
    if not result.stdout:
        return False

    try:
        meta = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return False

    # Подменяем техническое имя на оригинальное
    if original_name:
        meta['SourceFile'] = original_name
        meta['FileName']   = original_name

    with open(report_name, "w", encoding="utf-8") as f:
        f.write("╔══════════════════════════════╗\n")
        f.write("║       КРАТКИЙ ОТЧЁТ          ║\n")
        f.write("╚══════════════════════════════╝\n\n")

        # Файл
        f.write("📁 ФАЙЛ\n")
        f.write(f"  Имя        : {meta.get('FileName', '—')}\n")
        f.write(f"  Размер     : {meta.get('FileSize', '—')}\n")
        f.write(f"  Тип        : {meta.get('FileType', '—')}\n")
        w = meta.get('ImageWidth', '')
        h = meta.get('ImageHeight', '')
        if w and h:
            f.write(f"  Разрешение : {w}×{h} px\n")

        # Даты
        f.write("\n📅 ДАТЫ\n")
        f.write(f"  Создан  : {meta.get('FileCreateDate', '—')}\n")
        f.write(f"  Изменён : {meta.get('FileModifyDate', '—')}\n")

        # Устройство (только если есть)
        make     = meta.get('Make', '')
        model    = meta.get('Model', '')
        software = meta.get('Software', '')
        if make or model or software:
            f.write("\n📷 УСТРОЙСТВО\n")
            if make:     f.write(f"  Производитель : {make}\n")
            if model:    f.write(f"  Модель        : {model}\n")
            if software: f.write(f"  Программа     : {software}\n")

        # GPS (только если есть)
        lat = meta.get('GPSLatitude', '')
        lon = meta.get('GPSLongitude', '')
        if lat and lon:
            f.write("\n📍 ГЕОЛОКАЦИЯ\n")
            f.write(f"  Широта  : {lat}\n")
            f.write(f"  Долгота : {lon}\n")
            alt = meta.get('GPSAltitude', '')
            if alt:
                f.write(f"  Высота  : {alt}\n")

        # AI / C2PA
        f.write("\n🤖 AI / C2PA\n")
        if meta.get('JUMDLabel') == 'c2pa':
            generator = meta.get('Claim_Generator_InfoName', '')
            agent     = meta.get('ActionsSoftwareAgentName', '')
            agent_v   = meta.get('ActionsSoftwareAgentVersion', '')
            source    = meta.get('ActionsDigitalSourceType', '')
            src_key   = source.split('/')[-1] if source else ''
            src_label = C2PA_SOURCE_LABELS.get(src_key, src_key)

            f.write(f"  C2PA-маркировка : ✅ Обнаружена\n")
            if generator: f.write(f"  Генератор       : {generator}\n")
            if agent:     f.write(f"  Агент           : {agent} v{agent_v}\n")
            if src_label: f.write(f"  Тип источника   : {src_label}\n")
        else:
            f.write(f"  C2PA-маркировка : ❌ Не обнаружена\n")

    return True


def execute_clean(filepath: str) -> int:
    """Удаляет метаданные. Возвращает returncode exiftool (0=чисто, 1=с предупреждениями)."""
    result = subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", filepath],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=15
    )
    # Код 2+ — реальная ошибка, файл не обработан
    if result.returncode >= 2:
        raise RuntimeError(result.stderr.strip() or "exiftool: неизвестная ошибка")
    return result.returncode  # 0 или


def execute_extract(filepath: str, report_name: str) -> bool:
    """Ищет манифест C2PA через ExifTool."""
    result = subprocess.run(
        ["exiftool", "-j", filepath],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=15
    )

    if not result.stdout.strip():
        return False

    try:
        meta = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return False

    if meta.get('JUMDLabel') != 'c2pa':
        return False

    SKIP = {'Salt', 'Hash', 'Certificate', 'Ocsp', 'Pad', 'Item', 'Sig'}
    c2pa_fields = {
        k: v for k, v in meta.items()
        if any(x in k for x in ('JUMD', 'C2PA', 'Actions', 'Claim', 'Instance'))
        and not any(s in k for s in SKIP)
    }

    if not c2pa_fields:
        return False

    digital_source_url = meta.get('ActionsDigitalSourceType', '')
    source_label = next(
        (label for key, label in C2PA_SOURCE_LABELS.items() if key in digital_source_url),
        digital_source_url
    )

    actions = meta.get('ActionsAction', [])
    times   = meta.get('ActionsWhen', [])
    agent   = meta.get('ActionsSoftwareAgentName', 'N/A')
    agent_v = meta.get('ActionsSoftwareAgentVersion', '')
    tool    = meta.get('Claim_Generator_InfoName', 'N/A')
    spec    = meta.get('Claim_Generator_InfoSpecVersion', 'N/A')
    iid     = meta.get('InstanceID', 'N/A')

    with open(report_name, "w", encoding="utf-8") as f:
        f.write("╔══════════════════════════════╗\n")
        f.write("║       C2PA MANIFEST          ║\n")
        f.write("╚══════════════════════════════╝\n\n")

        f.write("[Генератор контента]\n")
        f.write(f"  Инструмент : {tool}\n")
        f.write(f"  Агент      : {agent} v{agent_v}\n")
        f.write(f"  Спека C2PA : {spec}\n\n")

        f.write("[Тип источника]\n")
        f.write(f"  {source_label}\n\n")

        f.write("[Действия]\n")
        if isinstance(actions, list):
            for i, action in enumerate(actions):
                when = times[i] if isinstance(times, list) and i < len(times) else ''
                f.write(f"  {action}  {when}\n")
        else:
            f.write(f"  {actions}\n")

        f.write(f"\n[Instance ID]\n  {iid}\n")

    return True