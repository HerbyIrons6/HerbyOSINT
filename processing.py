import os
import json
import subprocess


def execute_check(filepath: str, report_name: str) -> bool:
    """Извлекает метаданные и записывает их в TXT-файл."""
    print(f"[DEBUG] Запуск ExifTool для файла: {filepath}")

    # Для Windows лучше явно указывать расширение .exe
    cmd = "exiftool.exe" if os.name == 'nt' else "exiftool"

    try:
        result = subprocess.run(
            [cmd, "-j", filepath],
            capture_output=True,
            text=True,
            timeout=15
        )

        print(f"[DEBUG] Код возврата (returncode): {result.returncode}")
        if result.stderr:
            print(f"[DEBUG] Ошибки ExifTool (stderr): {result.stderr.strip()}")

        if not result.stdout:
            print("[DEBUG] ExifTool вернул пустой stdout.")
            return False

        meta_json = json.loads(result.stdout)[0]
        with open(report_name, "w", encoding="utf-8") as f:
            for key, value in meta_json.items():
                f.write(f"{key}: {value}\n")

        return True

    except FileNotFoundError:
        print(f"[DEBUG] Критическая ошибка: файл {cmd} не найден в директории проекта.")
        return False


def execute_clean(filepath: str) -> None:
    """Удаляет метаданные из файла (с перезаписью исходника)."""
    subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", filepath],
        timeout=15,
        check=True
    )


def execute_extract(filepath: str, report_name: str) -> bool:
    """Ищет манифест C2PA и записывает результат в TXT-файл."""
    print(f"[DEBUG] Запуск c2patool для файла: {filepath}")
    cmd = "c2patool.exe" if os.name == 'nt' else "c2patool"

    result = subprocess.run(
        [cmd, filepath],
        capture_output=True,
        text=True,
        encoding="utf-8",  # Защита от ошибок чтения кириллицы в Windows
        timeout=15
    )

    print(f"[DEBUG] c2patool returncode: {result.returncode}")
    if result.stderr:
        print(f"[DEBUG] c2patool stderr: {result.stderr.strip()}")

    # c2patool выводит манифест в stdout даже если крипто-подпись повреждена.
    # Если манифеста физически нет, он пишет "No c2pa/C2PA data found"
    output = result.stdout.strip()

    if not output or "No C2PA data" in output or "No c2pa data" in output:
        # Проверяем и stderr на случай системных ошибок
        if "No such file" in result.stderr:
            print("[DEBUG] Ошибка пути: c2patool не смог прочитать файл из-за спецсимволов.")
        return False

    with open(report_name, "w", encoding="utf-8") as f:
        f.write(output)

    return True