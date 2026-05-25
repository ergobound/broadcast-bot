from telethon import TelegramClient, events, functions, types, errors
from functools import wraps
import asyncio
from dotenv import load_dotenv
import loguru
import os, sys, logging
import random
load_dotenv()
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logging.getLogger("telethon").setLevel(logging.INFO)
# logging.getLogger("httpx").setLevel(logging.WARNING)

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")

session = 'user'
phonetest = ""

class TClient:

    def __init__(self, session, api_id, api_hash, username=None, userid=None, **kwargs):
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.username = username
        self.userid = userid
        self.kwargs = kwargs
        self.phone = None
        self.decorators_init()
    
    def __getattr__(self, name):
        # Если атрибут/метод не найден в текущем классе, поиск пойдет внутри объекта self.client
        return getattr(self.client, name)

    @classmethod
    async def create(cls, session, api_id, api_hash, username=None, userid=None, **kwargs):
        # создание пустого экземляра класса "вручную"
        self = cls(session, api_id, api_hash, username, userid, **kwargs)
        await self.build()
        return self

    async def build(self):
        self.client = TelegramClient(self.session, self.api_id, self.api_hash, *self.kwargs)
        await self.save_phone()

    async def is_authorized(self) -> bool:
        await self.connect()
        result = await self.client.is_user_authorized()
        await self.disconnect()
        return result
    
    async def send_code(self, phone) -> str | None:
        await self.connect()
        if await self.client.is_user_authorized():
            await self.client.log_out()
            await self.build()
            await self.connect()

        sendcode = await self.client.send_code_request(phone)
        return sendcode.phone_code_hash
        
    async def sign(self, phone=None, code=None, phone_code_hash=None, password=None) -> bool | None:
        # connect уже должен быть произведен в send_code
        await self.client.sign_in(phone, code, phone_code_hash=phone_code_hash, password=password)
    
    async def send_message(self, entity, text):
        await self.connect()
        try:
            await self.client.get_entity(entity)
        except ValueError as err:
            if "Cannot find any entity corresponding to" in str(err):
                await self.add_contact_phone(entity)     
            else:
                raise # В случае если ошибка не связана с невозможностью найти entity
        
        result = await self.client.send_message(entity, text)
        await self.disconnect()
        await asyncio.sleep(random.randint(1, 5)) # чтобы не было непрерывных сообщений, обход детекта телеграма
        # Здесь нужно исключение аннулированной сессии, чтобы ее пересоздать self.build() (Вероятно такой ошибки нет)

    async def add_contact_phone(self, phone) -> bool:
        await self.connect()
        result = await self.client(
            functions.contacts.ImportContactsRequest(
                contacts=[
                    types.InputPhoneContact(
                        client_id=random.randrange(-2**63, 2**63),
                        phone=phone, first_name='', last_name='',
        )]))
        if result.users:
            logging.info(f"{phone} добавлен в список контактов")
            return True
        else:
            logging.info(result.stringify())
            logging.info(f"Не удалось добавить {phone} в список контактов. {await self.info()}")
            raise AddContactInvalid(f"Контакт {phone} не найден. Вероятно он закрыл поиск по номеру телефона.\n")
    
    async def save_phone(self) -> str | None:
        if await self.is_authorized():
            await self.connect() # почему-то ему здесь надо после is_authori
            get_me = await self.client.get_me()
            self.phone = get_me.phone
            await self.disconnect()
            return get_me.phone
    
    async def connect(self):
        if not self.client.is_connected():
            await self.client.connect()
    
    async def disconnect(self):
        if self.client.is_connected():
            await self.client.disconnect()

    async def info(self):
        info = f"username: {self.username}, userid: {self.userid}, phone: {self.phone}"
        return info
    
    async def terminal_login(self, phone):
        """method for login test in terminal"""
        phone_code_hash = await self.send_code(phone)
        code = input("code: ")
        try:
            await self.sign(phone, code, phone_code_hash)
        except errors.SessionPasswordNeededError:
            password = input("password: ")
            await self.sign(password=password)
        
    def decorators_init(self):
        self.is_authorized = self.catch_error(self.is_authorized)
        self.send_code = self.catch_error(self.send_code)
        self.sign = self.catch_error(self.sign)
        self.send_message = self.catch_error(self.send_message)
        self.add_contact_phone = self.catch_error(self.add_contact_phone)
        # self.save_phone = self.catch_error(self.save_phone)

    def catch_error(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except errors.SessionPasswordNeededError as err:
                raise err # Это не совсем ошибка, нужно передать это состояние далее для ввода пароля
            except errors.FloodWaitError as err:
                seconds = "".join([s for s in str(err) if s.isnumeric()])
                err.args = (f"Флуд контроль. Ограничение будет снято через: {seconds}sec", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err 
            except errors.AuthKeyUnregisteredError as err:
                err.args = ("Необходима авторизация аккаунта телеграм.", str(err))
                logging.error(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}", exc_info=True)
                raise err
            except (errors.SessionExpiredError, errors.SessionRevokedError) as err:
                err.args = ("Необходима авторизация аккаунта телеграм.", str(err))
                logging.error(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}", exc_info=True)
                raise err
            except (errors.PhoneNumberInvalidError, errors.PhoneNumberUnoccupiedError) as err:
                err.args = ("Неверный номер телефона", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except errors.UserPrivacyRestrictedError as err:
                err.args = ("Настройки приватности пользователя запрещает отправку ему сообщений", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except errors.UserIsBlockedError as err:
                err.args = ("Невозможно отправить сообщение. Пользователь заблокировал вас", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except (errors.CodeHashInvalidError, errors.HashInvalidError) as err:
                err.args = ("Несоответствие хэша кода", str(err))
                logging.error(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}", exc_info=True)
                raise err
            except errors.PhoneCodeExpiredError as err:
                err.args = ("Код устарел", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except errors.PhoneCodeInvalidError as err:
                err.args = ("Неверный код", str(err))
                logging.error(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except errors.PasswordHashInvalidError as err:
                err.args = ("Неверный облачный пароль", str(err))
                logging.info(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}")
                raise err
            except BaseException as err:
                err.args = ("Неизвестная ошибка.", str(err))
                logging.error(f"{type(err).__name__}: {err.args[1]} | {err.args[0]} | {await self.info()}", exc_info=True)
                raise err
        return wrapper
    
    
class AddContactInvalid(Exception):
    pass

tclient = TClient(session, api_id, api_hash)

async def main():
    await tclient.terminal_login(phonetest)

if __name__ == "__main__":
    asyncio.run(main())