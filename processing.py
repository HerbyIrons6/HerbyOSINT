import json
import subprocess


def execute_check(filepath: str, report_name: str) -> bool:
    """Извлекает метаданные и записывает их в TXT-файл."""
    result = subprocess.run(
        ["exiftool", "-j", filepath],
        capture_output=True,
        text=True,
        timeout=15
    )

    if not result.stdout:
        return False

    meta_json = json.loads(result.stdout)[0]
    with open(report_name, "w", encoding="utf-8") as f:
        for key, value in meta_json.items():
            f.write(f"{key}: {value}\n")

    return True


def execute_clean(filepath: str) -> None:
    """Удаляет метаданные из файла (с перезаписью исходника)."""
    subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", filepath],
        timeout=15,
        check=True
    )


def execute_extract(filepath: str, report_name: str) -> bool:
    """Ищет манифест C2PA и записывает результат в TXT-файл."""
    result = subprocess.run(
        ["c2patool", filepath],
        capture_output=True,
        text=True,
        timeout=15
    )

    if "No C2PA data found" in result.stdout or not result.stdout.strip():
        return False

    with open(report_name, "w", encoding="utf-8") as f:
        f.write(result.stdout)

    return True