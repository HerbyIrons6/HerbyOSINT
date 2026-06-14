import json
import subprocess

C2PA_SOURCE_LABELS = {
    'trainedAlgorithmicMedia': '🤖 AI-генерація (trainedAlgorithmicMedia)',
    'compositeSynthetic':      '🔀 Синтетичний композит',
    'algorithmicMedia':        '⚙️ Алгоритмічне медіа',
    'digitalCapture':          '📷 Оригінальна цифрова зйомка',
    'minorHumanEdits':         '✏️ Редагування людиною',
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

    if original_name:
        meta['SourceFile'] = original_name
        meta['FileName']   = original_name

    with open(report_name, "w", encoding="utf-8") as f:
        f.write("╔══════════════════════════════╗\n")
        f.write("║        FULL REPORT           ║\n")
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

    if original_name:
        meta['SourceFile'] = original_name
        meta['FileName']   = original_name

    with open(report_name, "w", encoding="utf-8") as f:
        f.write("╔══════════════════════════════╗\n")
        f.write("║        SHORT REPORT          ║\n")
        f.write("╚══════════════════════════════╝\n\n")

        f.write("📁 FILE\n")
        f.write(f"  Name       : {meta.get('FileName', '—')}\n")
        f.write(f"  Size       : {meta.get('FileSize', '—')}\n")
        f.write(f"  Type       : {meta.get('FileType', '—')}\n")
        w = meta.get('ImageWidth', '')
        h = meta.get('ImageHeight', '')
        if w and h:
            f.write(f"  Resolution : {w}×{h} px\n")

        f.write("\n📅 DATES\n")
        f.write(f"  Created  : {meta.get('FileCreateDate', '—')}\n")
        f.write(f"  Modified : {meta.get('FileModifyDate', '—')}\n")

        make     = meta.get('Make', '')
        model    = meta.get('Model', '')
        software = meta.get('Software', '')
        if make or model or software:
            f.write("\n📷 DEVICE\n")
            if make:     f.write(f"  Make     : {make}\n")
            if model:    f.write(f"  Model    : {model}\n")
            if software: f.write(f"  Software : {software}\n")

        lat = meta.get('GPSLatitude', '')
        lon = meta.get('GPSLongitude', '')
        if lat and lon:
            f.write("\n📍 GEOLOCATION\n")
            f.write(f"  Lat : {lat}\n")
            f.write(f"  Lon : {lon}\n")
            alt = meta.get('GPSAltitude', '')
            if alt:
                f.write(f"  Alt : {alt}\n")

        f.write("\n🤖 AI / C2PA\n")
        if meta.get('JUMDLabel') == 'c2pa':
            generator = meta.get('Claim_Generator_InfoName', '')
            agent     = meta.get('ActionsSoftwareAgentName', '')
            agent_v   = meta.get('ActionsSoftwareAgentVersion', '')
            source    = meta.get('ActionsDigitalSourceType', '')
            src_key   = source.split('/')[-1] if source else ''
            src_label = C2PA_SOURCE_LABELS.get(src_key, src_key)

            f.write(f"  C2PA Mark : ✅ Found\n")
            if generator: f.write(f"  Generator : {generator}\n")
            if agent:     f.write(f"  Agent     : {agent} v{agent_v}\n")
            if src_label: f.write(f"  Source    : {src_label}\n")
        else:
            f.write(f"  C2PA Mark : ❌ Not found\n")

    return True

def execute_clean(filepath: str) -> int:
    result = subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", filepath],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=15
    )
    if result.returncode >= 2:
        raise RuntimeError(result.stderr.strip() or "exiftool: unknown error")
    return result.returncode

def execute_extract(filepath: str, report_name: str) -> bool:
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
        f.write("║        C2PA MANIFEST         ║\n")
        f.write("╚══════════════════════════════╝\n\n")

        f.write("[Content Generator]\n")
        f.write(f"  Tool  : {tool}\n")
        f.write(f"  Agent : {agent} v{agent_v}\n")
        f.write(f"  Spec  : C2PA {spec}\n\n")

        f.write("[Source Type]\n")
        f.write(f"  {source_label}\n\n")

        f.write("[Actions]\n")
        if isinstance(actions, list):
            for i, action in enumerate(actions):
                when = times[i] if isinstance(times, list) and i < len(times) else ''
                f.write(f"  {action}  {when}\n")
        else:
            f.write(f"  {actions}\n")

        f.write(f"\n[Instance ID]\n  {iid}\n")

    return True