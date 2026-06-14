MAGIC_NUMBERS = {
    b'\xFF\xD8\xFF': 'JPEG',
    b'\x89PNG\r\n\x1a\n': 'PNG',
    b'GIF87a': 'GIF',
    b'GIF89a': 'GIF',
    b'%PDF-': 'PDF',
    b'\x00\x00\x00 ftyp': 'MP4/MOV',
    b'\x00\x00\x00\x18ftyp': 'MP4/MOV',
    b'\x00\x00\x00\x20ftyp': 'MP4/MOV',
    b'RIFF': 'WAV/AVI/WEBP',
    b'ID3': 'MP3',
    b'\xFF\xFB': 'MP3',
    b'PK\x03\x04': 'ZIP/DOCX/XLSX', # Office-документи
}

def is_safe_file(filepath: str) -> bool:
    """Перевіряє справжній формат файлу за першими байтами (захист від маскування)."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(8)
            for magic in MAGIC_NUMBERS:
                if header.startswith(magic):
                    return True
        return False
    except Exception:
        return False