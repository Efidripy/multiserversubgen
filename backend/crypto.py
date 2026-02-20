"""
Модуль шифрования паролей узлов 3X-UI
Использует Fernet из cryptography для симметричного шифрования
"""
import os
import base64
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken


# Путь к ключу шифрования
KEY_FILE = "/opt/sub-manager/.encryption_key"


def generate_key() -> bytes:
    """Генерировать новый ключ шифрования"""
    return Fernet.generate_key()


def load_key() -> Optional[bytes]:
    """Загрузить существующий ключ из файла"""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    return None


def save_key(key: bytes) -> None:
    """Сохранить ключ в файл с ограниченными правами"""
    os.makedirs(os.path.dirname(KEY_FILE) or ".", exist_ok=True)
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(KEY_FILE, 0o600)  # Только чтение/запись для владельца


def get_or_generate_key() -> bytes:
    """Получить существующий ключ или создать новый"""
    key = load_key()
    if key is None:
        key = generate_key()
        save_key(key)
    return key


def encrypt_password(password: str, fernet: Fernet) -> str:
    """Зашифровать пароль"""
    if not password:
        return ""
    encrypted = fernet.encrypt(password.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_password(encrypted_password: str, fernet: Fernet) -> str:
    """Расшифровать пароль"""
    if not encrypted_password:
        return ""
    try:
        encrypted = base64.urlsafe_b64decode(encrypted_password.encode())
        return fernet.decrypt(encrypted).decode()
    except (InvalidToken, ValueError):
        # Если не удается расшифровать, возможно это не зашифрованный пароль (старый формат)
        # В этом случае возвращаем как есть (для миграции)
        return encrypted_password


def is_encrypted(value: str) -> bool:
    """Проверить, является ли значение зашифрованным"""
    try:
        base64.urlsafe_b64decode(value.encode())
        return True
    except:
        return False


# Глобальный экземпляр Fernet (инициализируется при импорте)
_fernet: Optional[Fernet] = None


def get_fernet() -> Fernet:
    """Получить экземпляр Fernet (ленивая инициализация)"""
    global _fernet
    if _fernet is None:
        key = get_or_generate_key()
        _fernet = Fernet(key)
    return _fernet


def encrypt(value: str) -> str:
    """Удобная обёртка для шифрования"""
    f = get_fernet()
    return encrypt_password(value, f)


def decrypt(value: str) -> str:
    """Удобная обёртка для дешифрования"""
    f = get_fernet()
    return decrypt_password(value, f)