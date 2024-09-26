# 导入所需的库
import base64
import hashlib
import json
import logging
import mimetypes
import os
import requests
import uuid
from datetime import datetime
from fake_useragent import UserAgent
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_apscheduler import APScheduler
from flask_cors import CORS, cross_origin
from io import BytesIO
from logging.handlers import TimedRotatingFileHandler
from queue import Queue
from urllib.parse import urlparse


# 读取配置文件
def load_config(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


CONFIG = load_config('./data/config.json')

LOG_LEVEL = CONFIG.get('log_level', 'INFO').upper()
NEED_LOG_TO_FILE = CONFIG.get('need_log_to_file', 'true').lower() == 'true'

# 使用 get 方法获取配置项，同时提供默认值
BASE_URL = CONFIG.get('upstream_base_url', '')
PROXY_API_PREFIX = CONFIG.get('upstream_api_prefix', '')

UPLOAD_BASE_URL = CONFIG.get('backend_container_url', '')
KEY_FOR_GPTS_INFO = CONFIG.get('key_for_gpts_info', '')
KEY_FOR_GPTS_INFO_ACCESS_TOKEN = CONFIG.get('key_for_gpts_info', '')
API_PREFIX = CONFIG.get('backend_container_api_prefix', '')
GPT_4_S_New_Names = CONFIG.get('gpt_4_s_new_name', 'gpt-4-s').split(',')
GPT_4_MOBILE_NEW_NAMES = CONFIG.get('gpt_4_mobile_new_name', 'gpt-4-mobile').split(',')
GPT_3_5_NEW_NAMES = CONFIG.get('gpt_3_5_new_name', 'gpt-3.5-turbo').split(',')
GPT_4_O_NEW_NAMES = CONFIG.get('gpt_4_o_new_name', 'gpt-4o').split(',')
GPT_4_O_MINI_NEW_NAMES = CONFIG.get('gpt_4_o_mini_new_name', 'gpt-4o-mini').split(',')
O1_PREVIEW_NEW_NAMES = CONFIG.get('o1_preview_new_name', 'o1-preview').split(',')
O1_MINI_NEW_NAMES = CONFIG.get('o1_mini_new_name', 'o1-mini').split(',')
UPLOAD_SUCCESS_TEXT = CONFIG.get('upload_success_text', "`🤖 文件上传成功，搜索将不再提供额外信息！`\n")

BOT_MODE = CONFIG.get('bot_mode', {})
BOT_MODE_ENABLED = BOT_MODE.get('enabled', 'false').lower() == 'true'
BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT = BOT_MODE.get('enabled_markdown_image_output', 'false').lower() == 'true'
BOT_MODE_ENABLED_BING_REFERENCE_OUTPUT = BOT_MODE.get('enabled_bing_reference_output', 'false').lower() == 'true'
BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT = BOT_MODE.get('enabled_plugin_output', 'false').lower() == 'true'

BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT = BOT_MODE.get('enabled_plain_image_url_output', 'false').lower() == 'true'

# oaiFreeToV1Api_refresh
REFRESH_TOACCESS = CONFIG.get('refresh_ToAccess', {})
REFRESH_TOACCESS_ENABLEOAI = REFRESH_TOACCESS.get('enableOai', 'true').lower() == 'true'
REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL = REFRESH_TOACCESS.get('oaifree_refreshToAccess_Url', '')
STEAM_SLEEP_TIME = REFRESH_TOACCESS.get('steam_sleep_time', 0)

NEED_DELETE_CONVERSATION_AFTER_RESPONSE = CONFIG.get('need_delete_conversation_after_response',
                                                     'true').lower() == 'true'

USE_OAIUSERCONTENT_URL = CONFIG.get('use_oaiusercontent_url', 'false').lower() == 'true'

# USE_PANDORA_FILE_SERVER = CONFIG.get('use_pandora_file_server', 'false').lower() == 'true'

CUSTOM_ARKOSE = CONFIG.get('custom_arkose_url', 'false').lower() == 'true'

ARKOSE_URLS = CONFIG.get('arkose_urls', "")

DALLE_PROMPT_PREFIX = CONFIG.get('dalle_prompt_prefix', '')

# redis配置读取
REDIS_CONFIG = CONFIG.get('redis', {})
REDIS_CONFIG_HOST = REDIS_CONFIG.get('host', 'redis')
REDIS_CONFIG_PORT = REDIS_CONFIG.get('port', 6379)
REDIS_CONFIG_PASSWORD = REDIS_CONFIG.get('password', '')
REDIS_CONFIG_DB = REDIS_CONFIG.get('db', 0)
REDIS_CONFIG_POOL_SIZE = REDIS_CONFIG.get('pool_size', 10)
REDIS_CONFIG_POOL_TIMEOUT = REDIS_CONFIG.get('pool_timeout', 30)

# 定义全部变量，用于缓存refresh_token和access_token
# 其中refresh_token 为 key
# access_token 为 value
refresh_dict = {}

# 设置日志级别
log_level_dict = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')

logger = logging.getLogger()
logger.setLevel(log_level_dict.get(LOG_LEVEL, logging.DEBUG))

import redis

# 假设您已经有一个Redis客户端的实例
redis_client = redis.StrictRedis(host=REDIS_CONFIG_HOST,
                                 port=REDIS_CONFIG_PORT,
                                 password=REDIS_CONFIG_PASSWORD,
                                 db=REDIS_CONFIG_DB,
                                 retry_on_timeout=True
                                 )

# 如果环境变量指示需要输出到文件
if NEED_LOG_TO_FILE:
    log_filename = './log/access.log'
    file_handler = TimedRotatingFileHandler(log_filename, when="midnight", interval=1, backupCount=30)
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

# 添加标准输出流处理器（控制台输出）
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

# 创建FakeUserAgent对象
ua = UserAgent()

import threading

#  开启线程锁
lock = threading.Lock()


def getPROXY_API_PREFIX(lock):
    index = 0
    while True:
        with lock:
            if not PROXY_API_PREFIX:
                return None
            else:
                return "/" + (PROXY_API_PREFIX[index % len(PROXY_API_PREFIX)])


def generate_unique_id(prefix):
    # 生成一个随机的 UUID
    random_uuid = uuid.uuid4()
    # 将 UUID 转换为字符串，并移除其中的短横线
    random_uuid_str = str(random_uuid).replace('-', '')
    # 结合前缀和处理过的 UUID 生成最终的唯一 ID
    unique_id = f"{prefix}-{random_uuid_str}"
    return unique_id


def get_accessible_model_list():
    return [config['name'] for config in gpts_configurations]


def find_model_config(model_name):
    for config in gpts_configurations:
        if config['name'] == model_name:
            return config
    return None


# 从 gpts.json 读取配置
def load_gpts_config(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


# 官方refresh_token刷新access_token
def oaiGetAccessToken(refresh_token):
    logger.info("将通过这个网址请求access_token：https://auth0.openai.com/oauth/token")
    url = "https://auth0.openai.com/oauth/token"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "redirect_uri": "com.openai.chat://auth0.openai.com/ios/com.openai.chat/callback",
        "grant_type": "refresh_token",
        "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
        "refresh_token": refresh_token
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        # 如果响应的状态码不是 200，将引发 HTTPError 异常
        response.raise_for_status()

        # 拿到access_token
        json_response = response.json()
        access_token = json_response.get('access_token')

        # 检查 access_token 是否有效
        if not access_token or not access_token.startswith("eyJhb"):
            logger.error("access_token 无效.")
            return None

        return access_token

    except requests.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}")
    except Exception as err:
        logger.error(f"Other error occurred: {err}")
    return None


# oaiFree获得access_token
def oaiFreeGetAccessToken(getAccessTokenUrl, refresh_token):
    try:
        logger.info("将通过这个网址请求access_token：" + getAccessTokenUrl)
        data = {
            'refresh_token': refresh_token,
        }
        response = requests.post(getAccessTokenUrl, data=data)
        if not response.ok:
            logger.error("Request 失败: " + response.text.strip())
            return None
        access_token = None
        try:
            access_token = response.json()["access_token"]
        except json.JSONDecodeError:
            logger.exception("Failed to decode JSON response.")
        if response.status_code == 200 and access_token and access_token.startswith("eyJhb"):
            return access_token
    except Exception as e:
        logger.exception("获取access token失败.")
    return None


def updateGptsKey():
    global KEY_FOR_GPTS_INFO
    global KEY_FOR_GPTS_INFO_ACCESS_TOKEN
    if not KEY_FOR_GPTS_INFO == '' and not KEY_FOR_GPTS_INFO.startswith("eyJhb"):
        if REFRESH_TOACCESS_ENABLEOAI:
            access_token = oaiGetAccessToken(KEY_FOR_GPTS_INFO)
        else:
            access_token = oaiFreeGetAccessToken(REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL, KEY_FOR_GPTS_INFO)
        if access_token.startswith("eyJhb"):
            KEY_FOR_GPTS_INFO_ACCESS_TOKEN = access_token
            logging.info("KEY_FOR_GPTS_INFO_ACCESS_TOKEN被更新:" + KEY_FOR_GPTS_INFO_ACCESS_TOKEN)


# 根据 ID 发送请求并获取配置信息
def fetch_gizmo_info(base_url, proxy_api_prefix, model_id):
    url = f"{base_url}{proxy_api_prefix}/backend-api/gizmos/{model_id}"
    headers = {
        "Authorization": f"Bearer {KEY_FOR_GPTS_INFO_ACCESS_TOKEN}"
    }

    response = requests.get(url, headers=headers)
    # logger.debug(f"fetch_gizmo_info_response: {response.text}")
    if response.status_code == 200:
        return response.json()
    else:
        return None


# gpts_configurations = []

# 将配置添加到全局列表
def add_config_to_global_list(base_url, proxy_api_prefix, gpts_data):
    global gpts_configurations
    updateGptsKey()  # cSpell:ignore Gpts
    # print(f"gpts_data: {gpts_data}")
    for model_name, model_info in gpts_data.items():
        # print(f"model_name: {model_name}")
        # print(f"model_info: {model_info}")
        model_id = model_info['id']
        # 首先尝试从 Redis 获取缓存数据
        cached_gizmo_info = redis_client.get(model_id)
        if cached_gizmo_info:
            gizmo_info = eval(cached_gizmo_info)  # 将字符串转换回字典
            logger.info(f"Using cached info for {model_name}, {model_id}")
        else:
            logger.info(f"Fetching gpts info for {model_name}, {model_id}")
            gizmo_info = fetch_gizmo_info(base_url, proxy_api_prefix, model_id)
            # 如果成功获取到数据，则将其存入 Redis
            if gizmo_info:
                redis_client.set(model_id, str(gizmo_info))
                logger.info(f"Cached gizmo info for {model_name}, {model_id}")

        # 检查模型名称是否已经在列表中
        if gizmo_info and not any(d['name'] == model_name for d in gpts_configurations):
            gpts_configurations.append({
                'name': model_name,
                'id': model_id,
                'config': gizmo_info
            })
        else:
            logger.info(f"Model already exists in the list, skipping...")


def generate_gpts_payload(model, messages):
    model_config = find_model_config(model)
    if model_config:
        gizmo_info = model_config['config']
        gizmo_id = gizmo_info['gizmo']['id']

        payload = {
            "action": "next",
            "messages": messages,
            "parent_message_id": str(uuid.uuid4()),
            "model": "gpt-4-gizmo",
            "timezone_offset_min": -480,
            "history_and_training_disabled": False,
            "conversation_mode": {
                "gizmo": gizmo_info,
                "kind": "gizmo_interaction",
                "gizmo_id": gizmo_id
            },
            "force_paragen": False,
            "force_rate_limit": False
        }
        return payload
    else:
        return None


# 创建 Flask 应用
app = Flask(__name__)
CORS(app, resources={r"/images/*": {"origins": "*"}})
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# PANDORA_UPLOAD_URL = 'files.pandoranext.com'


VERSION = '0.8.1'
# VERSION = 'test'
UPDATE_INFO = '👀 支持输出o1思考过程'
# UPDATE_INFO = '【仅供临时测试使用】 '

with app.app_context():
    global gpts_configurations  # 移到作用域的最开始

    # 输出版本信息
    logger.info(f"==========================================")
    logger.info(f"Version: {VERSION}")
    logger.info(f"Update Info: {UPDATE_INFO}")

    logger.info(f"LOG_LEVEL: {LOG_LEVEL}")
    logger.info(f"NEED_LOG_TO_FILE: {NEED_LOG_TO_FILE}")

    logger.info(f"BOT_MODE_ENABLED: {BOT_MODE_ENABLED}")

    if BOT_MODE_ENABLED:
        logger.info(f"enabled_markdown_image_output: {BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT}")
        logger.info(f"enabled_plain_image_url_output: {BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT}")
        logger.info(f"enabled_bing_reference_output: {BOT_MODE_ENABLED_BING_REFERENCE_OUTPUT}")
        logger.info(f"enabled_plugin_output: {BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT}")

    logger.info(f"REFRESH_TOACCESS_ENABLEOAI: {REFRESH_TOACCESS_ENABLEOAI}")

    if not REFRESH_TOACCESS_ENABLEOAI:
        logger.info(f"REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL : {REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL}")

    if BOT_MODE_ENABLED:
        logger.info(f"enabled_markdown_image_output: {BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT}")
        logger.info(f"enabled_plain_image_url_output: {BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT}")
        logger.info(f"enabled_bing_reference_output: {BOT_MODE_ENABLED_BING_REFERENCE_OUTPUT}")
        logger.info(f"enabled_plugin_output: {BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT}")

    # oaiFreeToV1Api_refresh

    logger.info(f"REFRESH_TOACCESS_ENABLEOAI: {REFRESH_TOACCESS_ENABLEOAI}")
    logger.info(f"REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL : {REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL}")
    logger.info(f"STEAM_SLEEP_TIME: {STEAM_SLEEP_TIME}")

    if not BASE_URL:
        raise Exception('upstream_base_url is not set')
    else:
        logger.info(f"upstream_base_url: {BASE_URL}")
    if not PROXY_API_PREFIX:
        logger.warning('upstream_api_prefix is not set')
    else:
        logger.info(f"upstream_api_prefix: {PROXY_API_PREFIX}")

    if USE_OAIUSERCONTENT_URL == False:
        # 检测./images和./files文件夹是否存在，不存在则创建
        if not os.path.exists('./images'):
            os.makedirs('./images')
        if not os.path.exists('./files'):
            os.makedirs('./files')

    if not UPLOAD_BASE_URL:
        if USE_OAIUSERCONTENT_URL:
            logger.info("backend_container_url 未设置，将使用 oaiusercontent.com 作为图片域名")
        else:
            logger.warning("backend_container_url 未设置，图片生成功能将无法正常使用")


    else:
        logger.info(f"backend_container_url: {UPLOAD_BASE_URL}")

    if not KEY_FOR_GPTS_INFO:
        logger.warning("key_for_gpts_info 未设置，请将 gpts.json 中仅保留 “{}” 作为内容")
    else:
        logger.info(f"key_for_gpts_info: {KEY_FOR_GPTS_INFO}")

    if not API_PREFIX:
        logger.warning("backend_container_api_prefix 未设置，安全性会有所下降")
        logger.info(f'Chat 接口 URI: /v1/chat/completions')
        logger.info(f'绘图接口 URI: /v1/images/generations')
    else:
        logger.info(f"backend_container_api_prefix: {API_PREFIX}")
        logger.info(f'Chat 接口 URI: /{API_PREFIX}/v1/chat/completions')
        logger.info(f'绘图接口 URI: /{API_PREFIX}/v1/images/generations')

    logger.info(f"need_delete_conversation_after_response: {NEED_DELETE_CONVERSATION_AFTER_RESPONSE}")

    logger.info(f"use_oaiusercontent_url: {USE_OAIUSERCONTENT_URL}")

    logger.info(f"use_pandora_file_server: False")

    logger.info(f"custom_arkose_url: {CUSTOM_ARKOSE}")

    if CUSTOM_ARKOSE:
        logger.info(f"arkose_urls: {ARKOSE_URLS}")

    logger.info(f"DALLE_prompt_prefix: {DALLE_PROMPT_PREFIX}")

    logger.info(f"==========================================")

    # 更新 gpts_configurations 列表，支持多个映射
    gpts_configurations = []
    for name in GPT_4_S_New_Names:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "gpt-4-s"
        })
    for name in GPT_4_MOBILE_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "gpt-4-mobile"
        })
    for name in GPT_3_5_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "gpt-3.5-turbo"
        })
    for name in GPT_4_O_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "gpt-4-o"
        })
    for name in GPT_4_O_MINI_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "gpt-4o-mini"
        })
    for name in O1_PREVIEW_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "o1-preview"
        })
    for name in O1_MINI_NEW_NAMES:
        gpts_configurations.append({
            "name": name.strip(),
            "ori_name": "o1-mini"
        })
    logger.info(f"GPTS 配置信息")

    # 加载配置并添加到全局列表
    gpts_data = load_gpts_config("./data/gpts.json")
    add_config_to_global_list(BASE_URL, getPROXY_API_PREFIX(lock), gpts_data)
    # print("当前可用GPTS：" + get_accessible_model_list())
    # 输出当前可用 GPTS name
    # 获取当前可用的 GPTS 模型列表
    accessible_model_list = get_accessible_model_list()
    logger.info(f"当前可用 GPTS 列表: {accessible_model_list}")

    # 检查列表中是否有重复的模型名称
    if len(accessible_model_list) != len(set(accessible_model_list)):
        raise Exception("检测到重复的模型名称，请检查环境变量或配置文件。")

    logger.info(f"==========================================")

    # print(f"GPTs Payload 生成测试")

    # print(f"gpt-4-classic: {generate_gpts_payload('gpt-4-classic', [])}")


# 定义获取 token 的函数
def get_token():
    # 从环境变量获取 URL 列表，并去除每个 URL 周围的空白字符
    api_urls = [url.strip() for url in ARKOSE_URLS.split(",")]

    for url in api_urls:
        if not url:
            continue

        full_url = f"{url}/api/arkose/token"
        payload = {'type': 'gpt-4'}

        try:
            response = requests.post(full_url, data=payload)
            if response.status_code == 200:
                token = response.json().get('token')
                # 确保 token 字段存在且不是 None 或空字符串
                if token:
                    logger.debug(f"成功从 {url} 获取 arkose token")
                    return token
                else:
                    logger.error(f"获取的 token 响应无效: {token}")
            else:
                logger.error(f"获取 arkose token 失败: {response.status_code}, {response.text}")
        except requests.RequestException as e:
            logger.error(f"请求异常: {e}")

    raise Exception("获取 arkose token 失败")


import os


def get_image_dimensions(file_content):
    with Image.open(BytesIO(file_content)) as img:
        return img.width, img.height


def determine_file_use_case(mime_type):
    multimodal_types = ["image/jpeg", "image/webp", "image/png", "image/gif"]
    my_files_types = ["text/x-php", "application/msword", "text/x-c", "text/html",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/json", "text/javascript", "application/pdf",
                      "text/x-java", "text/x-tex", "text/x-typescript", "text/x-sh",
                      "text/x-csharp", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                      "text/x-c++", "application/x-latext", "text/markdown", "text/plain",
                      "text/x-ruby", "text/x-script.python"]

    if mime_type in multimodal_types:
        return "multimodal"
    elif mime_type in my_files_types:
        return "my_files"
    else:
        return "ace_upload"


def upload_file(file_content, mime_type, api_key, proxy_api_prefix):
    logger.debug("文件上传开始")

    width = None
    height = None
    if mime_type.startswith('image/'):
        try:
            width, height = get_image_dimensions(file_content)
        except Exception as e:
            logger.error(f"图片信息获取异常, 切换为text/plain： {e}")
            mime_type = 'text/plain'

    # logger.debug(f"文件内容: {file_content}")
    file_size = len(file_content)
    logger.debug(f"文件大小: {file_size}")
    file_extension = get_file_extension(mime_type)
    logger.debug(f"文件扩展名: {file_extension}")
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    logger.debug(f"sha256_hash: {sha256_hash}")
    file_name = f"{sha256_hash}{file_extension}"
    logger.debug(f"文件名: {file_name}")

    logger.debug(f"Use Case: {determine_file_use_case(mime_type)}")

    if determine_file_use_case(mime_type) == "ace_upload":
        mime_type = ''
        logger.debug(f"非已知文件类型，MINE置空")

    # 第1步：调用/backend-api/files接口获取上传URL
    upload_api_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files"
    upload_request_payload = {
        "file_name": file_name,
        "file_size": file_size,
        "use_case": determine_file_use_case(mime_type)
    }
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    upload_response = requests.post(upload_api_url, json=upload_request_payload, headers=headers)
    logger.debug(f"upload_response: {upload_response.text}")
    if upload_response.status_code != 200:
        raise Exception("Failed to get upload URL")

    upload_data = upload_response.json()
    upload_url = upload_data.get("upload_url")
    logger.debug(f"upload_url: {upload_url}")
    file_id = upload_data.get("file_id")
    logger.debug(f"file_id: {file_id}")

    # 第2步：上传文件
    put_headers = {
        'Content-Type': mime_type,
        'x-ms-blob-type': 'BlockBlob'  # 添加这个头部
    }
    put_response = requests.put(upload_url, data=file_content, headers=put_headers)
    if put_response.status_code != 201:
        logger.debug(f"put_response: {put_response.text}")
        logger.debug(f"put_response status_code: {put_response.status_code}")
        raise Exception("Failed to upload file")

    # 第3步：检测上传是否成功并检查响应
    check_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files/{file_id}/uploaded"
    check_response = requests.post(check_url, json={}, headers=headers)
    logger.debug(f"check_response: {check_response.text}")
    if check_response.status_code != 200:
        raise Exception("Failed to check file upload completion")

    check_data = check_response.json()
    if check_data.get("status") != "success":
        raise Exception("File upload completion check not successful")

    return {
        "file_id": file_id,
        "file_name": file_name,
        "size_bytes": file_size,
        "mimeType": mime_type,
        "width": width,
        "height": height
    }


def get_file_metadata(file_content, mime_type, api_key, proxy_api_prefix):
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    logger.debug(f"sha256_hash: {sha256_hash}")
    # 首先尝试从Redis中获取数据
    cached_data = redis_client.get(sha256_hash)
    if cached_data is not None:
        # 如果在Redis中找到了数据，解码后直接返回
        logger.info(f"从Redis中获取到文件缓存数据")
        cache_file_data = json.loads(cached_data.decode())

        tag = True
        file_id = cache_file_data.get("file_id")
        # 检测之前的文件是否仍然有效
        check_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files/{file_id}/uploaded"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        check_response = requests.post(check_url, json={}, headers=headers)
        logger.debug(f"check_response: {check_response.text}")
        if check_response.status_code != 200:
            tag = False

        check_data = check_response.json()
        if check_data.get("status") != "success":
            tag = False
        if tag:
            logger.info(f"Redis中的文件缓存数据有效，将使用缓存数据")
            return cache_file_data
        else:
            logger.info(f"Redis中的文件缓存数据已失效，重新上传文件")

    else:
        logger.info(f"Redis中没有找到文件缓存数据")
    # 如果Redis中没有，上传文件并保存新数据
    new_file_data = upload_file(file_content, mime_type, api_key, proxy_api_prefix)
    mime_type = new_file_data.get('mimeType')
    # 为图片类型文件添加宽度和高度信息
    if mime_type.startswith('image/'):
        width, height = get_image_dimensions(file_content)
        new_file_data['width'] = width
        new_file_data['height'] = height

    # 将新的文件数据存入Redis
    redis_client.set(sha256_hash, json.dumps(new_file_data))

    return new_file_data


def get_file_extension(mime_type):
    # 基于 MIME 类型返回文件扩展名的映射表
    extension_mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "text/x-php": ".php",
        "application/msword": ".doc",
        "text/x-c": ".c",
        "text/html": ".html",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/json": ".json",
        "text/javascript": ".js",
        "application/pdf": ".pdf",
        "text/x-java": ".java",
        "text/x-tex": ".tex",
        "text/x-typescript": ".ts",
        "text/x-sh": ".sh",
        "text/x-csharp": ".cs",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/x-c++": ".cpp",
        "application/x-latext": ".latex",  # 这里可能需要根据实际情况调整
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/x-ruby": ".rb",
        "text/x-script.python": ".py",
        # 其他 MIME 类型和扩展名...
    }
    return extension_mapping.get(mime_type, mimetypes.guess_extension(mime_type))


my_files_types = [
    "text/x-php", "application/msword", "text/x-c", "text/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/json", "text/javascript", "application/pdf",
    "text/x-java", "text/x-tex", "text/x-typescript", "text/x-sh",
    "text/x-csharp", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/x-c++", "application/x-latext", "text/markdown", "text/plain",
    "text/x-ruby", "text/x-script.python"
]


# 定义发送请求的函数
def send_text_prompt_and_get_response(messages, api_key, account_id, stream, model, proxy_api_prefix):
    url = f"{BASE_URL}{proxy_api_prefix}/backend-api/conversation"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    # 查找模型配置
    model_config = find_model_config(model)
    ori_model_name = ''
    if model_config:
        # 检查是否有 ori_name
        ori_model_name = model_config.get('ori_name', model)

    formatted_messages = []
    # logger.debug(f"原始 messages: {messages}")
    for message in messages:
        message_id = str(uuid.uuid4())
        content = message.get("content")

        if isinstance(content, list) and ori_model_name not in ['gpt-3.5-turbo']:
            logger.debug(f"gpt-vision 调用")
            new_parts = []
            attachments = []
            contains_image = False  # 标记是否包含图片

            for part in content:
                if isinstance(part, dict) and "type" in part:
                    if part["type"] == "text":
                        new_parts.append(part["text"])
                    elif part["type"] == "image_url":
                        # logger.debug(f"image_url: {part['image_url']}")
                        file_url = part["image_url"]["url"]
                        if file_url.startswith('data:'):
                            # 处理 base64 编码的文件数据
                            mime_type, base64_data = file_url.split(';')[0], file_url.split(',')[1]
                            mime_type = mime_type.split(':')[1]
                            try:
                                file_content = base64.b64decode(base64_data)
                            except Exception as e:
                                logger.error(f"类型为 {mime_type} 的 base64 编码数据解码失败: {e}")
                                continue
                        else:
                            # 处理普通的文件URL
                            try:
                                tmp_user_agent = ua.random
                                logger.debug(f"随机 User-Agent: {tmp_user_agent}")
                                tmp_headers = {
                                    'User-Agent': tmp_user_agent
                                }
                                file_response = requests.get(url=file_url, headers=tmp_headers)
                                file_content = file_response.content
                                mime_type = file_response.headers.get('Content-Type', '').split(';')[0].strip()
                            except Exception as e:
                                logger.error(f"获取文件 {file_url} 失败: {e}")
                                continue

                        logger.debug(f"mime_type: {mime_type}")
                        file_metadata = get_file_metadata(file_content, mime_type, api_key, proxy_api_prefix)

                        mime_type = file_metadata["mimeType"]
                        logger.debug(f"处理后 mime_type: {mime_type}")

                        if mime_type.startswith('image/'):
                            contains_image = True
                            new_part = {
                                "asset_pointer": f"file-service://{file_metadata['file_id']}",
                                "size_bytes": file_metadata["size_bytes"],
                                "width": file_metadata["width"],
                                "height": file_metadata["height"]
                            }
                            new_parts.append(new_part)

                        attachment = {
                            "name": file_metadata["file_name"],
                            "id": file_metadata["file_id"],
                            "mimeType": file_metadata["mimeType"],
                            "size": file_metadata["size_bytes"]  # 添加文件大小
                        }

                        if mime_type.startswith('image/'):
                            attachment.update({
                                "width": file_metadata["width"],
                                "height": file_metadata["height"]
                            })
                        elif mime_type in my_files_types:
                            attachment.update({"fileTokenSize": len(file_metadata["file_name"])})

                        attachments.append(attachment)
                else:
                    # 确保 part 是字符串
                    text_part = str(part) if not isinstance(part, str) else part
                    new_parts.append(text_part)

            content_type = "multimodal_text" if contains_image else "text"
            formatted_message = {
                "id": message_id,
                "author": {"role": message.get("role")},
                "content": {"content_type": content_type, "parts": new_parts},
                "metadata": {"attachments": attachments}
            }
            formatted_messages.append(formatted_message)
            logger.critical(f"formatted_message: {formatted_message}")

        else:
            # 处理单个文本消息的情况
            formatted_message = {
                "id": message_id,
                "author": {"role": message.get("role")},
                "content": {"content_type": "text", "parts": [content]},
                "metadata": {}
            }
            formatted_messages.append(formatted_message)

    # logger.debug(f"formatted_messages: {formatted_messages}")
    # return
    payload = {}

    logger.info(f"model: {model}")

    # 查找模型配置
    model_config = find_model_config(model)
    if model_config or 'gpt-4-gizmo-' in model:
        # 检查是否有 ori_name
        if model_config:
            ori_model_name = model_config.get('ori_name', model)
            logger.info(f"原模型名: {ori_model_name}")
        else:
            logger.info(f"请求模型名: {model}")
            ori_model_name = model
        if ori_model_name == 'gpt-4-s':
            payload = {
                # 构建 payload
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "gpt-4",
                "timezone_offset_min": -480,
                "suggestions": [],
                "history_and_training_disabled": False,
                "conversation_mode": {"kind": "primary_assistant"}, "force_paragen": False, "force_rate_limit": False
            }
        elif ori_model_name == 'gpt-4-mobile':
            payload = {
                # 构建 payload
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "gpt-4",
                "timezone_offset_min": -480,
                "suggestions": [],
                "history_and_training_disabled": False,
                "conversation_mode": {"kind": "primary_assistant"}, "force_paragen": False, "force_rate_limit": False
            }
        elif ori_model_name == 'gpt-3.5-turbo':
            payload = {
                # 构建 payload
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "timezone_offset_min": -480,
                "suggestions": [
                    "What are 5 creative things I could do with my kids' art? I don't want to throw them away, "
                    "but it's also so much clutter.",
                    "I want to cheer up my friend who's having a rough day. Can you suggest a couple short and sweet "
                    "text messages to go with a kitten gif?",
                    "Come up with 5 concepts for a retro-style arcade game.",
                    "I have a photoshoot tomorrow. Can you recommend me some colors and outfit options that will look "
                    "good on camera?"
                ],
                "history_and_training_disabled": False,
                "arkose_token": None,
                "conversation_mode": {
                    "kind": "primary_assistant"
                },
                "force_paragen": False,
                "force_paragen_model_slug": "",
                "force_rate_limit": False
            }
        elif ori_model_name == 'gpt-4-o':
            payload = {
                # 构建 payload
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "gpt-4o",
                "timezone_offset_min": -480,
                "suggestions": [
                    "What are 5 creative things I could do with my kids' art? I don't want to throw them away, but it's also so much clutter.",
                    "I want to cheer up my friend who's having a rough day. Can you suggest a couple short and sweet text messages to go with a kitten gif?",
                    "Come up with 5 concepts for a retro-style arcade game.",
                    "I have a photoshoot tomorrow. Can you recommend me some colors and outfit options that will look good on camera?"
                ],
                "history_and_training_disabled": False,
                "arkose_token": None,
                "conversation_mode": {
                    "kind": "primary_assistant"
                },
                "force_paragen": False,
                "force_rate_limit": False
            }
        elif ori_model_name == 'gpt-4o-mini':
            payload = {
                # 构建 payload
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "timezone_offset_min": -480,
                "suggestions": [
                    "What are 5 creative things I could do with my kids' art? I don't want to throw them away, "
                    "but it's also so much clutter.",
                    "I want to cheer up my friend who's having a rough day. Can you suggest a couple short and sweet "
                    "text messages to go with a kitten gif?",
                    "Come up with 5 concepts for a retro-style arcade game.",
                    "I have a photoshoot tomorrow. Can you recommend me some colors and outfit options that will look "
                    "good on camera?"
                ],
                "history_and_training_disabled": False,
                "arkose_token": None,
                "conversation_mode": {
                    "kind": "primary_assistant"
                },
                "force_paragen": False,
                "force_paragen_model_slug": "",
                "force_rate_limit": False
            }
        elif ori_model_name == 'o1-preview':
            payload = {
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "o1-preview",
                "timezone_offset_min": -480,
                "suggestions": [
                    "What are 5 creative things I could do with my kids' art? I don't want to throw them away, "
                    "but it's also so much clutter.",
                    "I want to cheer up my friend who's having a rough day. Can you suggest a couple short and sweet "
                    "text messages to go with a kitten gif?",
                    "Come up with 5 concepts for a retro-style arcade game.",
                    "I have a photoshoot tomorrow. Can you recommend me some colors and outfit options that will look "
                    "good on camera?"
                ],
                "variant_purpose": "comparison_implicit",
                "history_and_training_disabled": False,
                "conversation_mode": {
                    "kind": "primary_assistant"
                },
                "force_paragen": False,
                "force_paragen_model_slug": "",
                "force_nulligen": False,
                "force_rate_limit": False,
                "reset_rate_limits": False,
                "force_use_sse": True,
            }
        elif ori_model_name == 'o1-mini':
            payload = {
                "action": "next",
                "messages": formatted_messages,
                "parent_message_id": str(uuid.uuid4()),
                "model": "o1-mini",
                "timezone_offset_min": -480,
                "suggestions": [
                    "What are 5 creative things I could do with my kids' art? I don't want to throw them away, "
                    "but it's also so much clutter.",
                    "I want to cheer up my friend who's having a rough day. Can you suggest a couple short and sweet "
                    "text messages to go with a kitten gif?",
                    "Come up with 5 concepts for a retro-style arcade game.",
                    "I have a photoshoot tomorrow. Can you recommend me some colors and outfit options that will look "
                    "good on camera?"
                ],
                "variant_purpose": "comparison_implicit",
                "history_and_training_disabled": False,
                "conversation_mode": {
                    "kind": "primary_assistant"
                },
                "force_paragen": False,
                "force_paragen_model_slug": "",
                "force_nulligen": False,
                "force_rate_limit": False,
                "reset_rate_limits": False,
                "force_use_sse": True,
            }

        elif 'gpt-4-gizmo-' in model:
            payload = generate_gpts_payload(model, formatted_messages)
            if not payload:
                global gpts_configurations
                # 假设 model是 'gpt-4-gizmo-123'
                split_name = model.split('gpt-4-gizmo-')
                model_id = split_name[1] if len(split_name) > 1 else None
                gizmo_info = fetch_gizmo_info(BASE_URL, proxy_api_prefix, model_id)
                logging.info(gizmo_info)

                # 如果成功获取到数据，则将其存入 Redis
                if gizmo_info:
                    redis_client.set(model_id, str(gizmo_info))
                    logger.info(f"Cached gizmo info for {model}, {model_id}")
                    # 检查模型名称是否已经在列表中
                    if not any(d['name'] == model for d in gpts_configurations):
                        gpts_configurations.append({
                            'name': model,
                            'id': model_id,
                            'config': gizmo_info
                        })
                    else:
                        logger.info(f"Model already exists in the list, skipping...")
                    payload = generate_gpts_payload(model, formatted_messages)
                else:
                    raise Exception('KEY_FOR_GPTS_INFO is not accessible')
        else:
            payload = generate_gpts_payload(model, formatted_messages)
            if not payload:
                raise Exception('model is not accessible')
        # 根据NEED_DELETE_CONVERSATION_AFTER_RESPONSE修改history_and_training_disabled
        if NEED_DELETE_CONVERSATION_AFTER_RESPONSE:
            logger.debug(f"是否保留会话: {NEED_DELETE_CONVERSATION_AFTER_RESPONSE == False}")
            payload['history_and_training_disabled'] = True
        if ori_model_name not in ['gpt-3.5-turbo']:
            if CUSTOM_ARKOSE:
                token = get_token()
                payload["arkose_token"] = token
                # 在headers中添加新字段
                headers["Openai-Sentinel-Arkose-Token"] = token

            # 用于调用ChatGPT Team次数
            if account_id:
                headers["ChatGPT-Account-ID"] = account_id

        logger.debug(f"headers: {headers}")
        logger.debug(f"payload: {payload}")
        response = requests.post(url, headers=headers, json=payload, stream=True)
        # print(response)
        return response


def delete_conversation(conversation_id, api_key, proxy_api_prefix):
    logger.info(f"准备删除的会话id： {conversation_id}")
    if not NEED_DELETE_CONVERSATION_AFTER_RESPONSE:
        logger.info(f"自动删除会话功能已禁用")
        return
    if conversation_id and NEED_DELETE_CONVERSATION_AFTER_RESPONSE:
        patch_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/conversation/{conversation_id}"
        patch_headers = {
            "Authorization": f"Bearer {api_key}",
        }
        patch_data = {"is_visible": False}
        response = requests.patch(patch_url, headers=patch_headers, json=patch_data)

        if response.status_code == 200:
            logger.info(f"删除会话 {conversation_id} 成功")
        else:
            logger.error(f"PATCH 请求失败: {response.text}")


from PIL import Image
import io


def save_image(image_data, path='images'):
    try:
        # print(f"image_data: {image_data}")
        if not os.path.exists(path):
            os.makedirs(path)
        current_time = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f'image_{current_time}.png'
        full_path = os.path.join(path, filename)
        logger.debug(f"完整的文件路径: {full_path}")  # 打印完整路径
        # print(f"filename: {filename}")
        # 使用 PIL 打开图像数据
        with Image.open(io.BytesIO(image_data)) as image:
            # 保存为 PNG 格式
            image.save(os.path.join(path, filename), 'PNG')

        logger.debug(f"保存图片成功: {filename}")

        return os.path.join(path, filename)
    except Exception as e:
        logger.error(f"保存图片时出现异常: {e}")


def unicode_to_chinese(unicode_string):
    # 首先将字符串转换为标准的 JSON 格式字符串
    json_formatted_str = json.dumps(unicode_string)
    # 然后将 JSON 格式的字符串解析回正常的字符串
    return json.loads(json_formatted_str)


import re


# 辅助函数：检查是否为合法的引用格式或正在构建中的引用格式
def is_valid_citation_format(text):
    # 完整且合法的引用格式，允许紧跟另一个起始引用标记
    if re.fullmatch(r'\u3010\d+\u2020(source|\u6765\u6e90)\u3011\u3010?', text):
        return True

    # 完整且合法的引用格式

    if re.fullmatch(r'\u3010\d+\u2020(source|\u6765\u6e90)\u3011', text):
        return True

    # 合法的部分构建格式
    if re.fullmatch(r'\u3010(\d+)?(\u2020(source|\u6765\u6e90)?)?', text):
        return True

    # 不合法的格式
    return False


# 辅助函数：检查是否为完整的引用格式
# 检查是否为完整的引用格式
def is_complete_citation_format(text):
    return bool(re.fullmatch(r'\u3010\d+\u2020(source|\u6765\u6e90)\u3011\u3010?', text))


# 替换完整的引用格式
def replace_complete_citation(text, citations):
    def replace_match(match):
        citation_number = match.group(1)
        for citation in citations:
            cited_message_idx = citation.get('metadata', {}).get('extra', {}).get('cited_message_idx')
            logger.debug(f"cited_message_idx: {cited_message_idx}")
            logger.debug(f"citation_number: {citation_number}")
            logger.debug(f"is citation_number == cited_message_idx: {cited_message_idx == int(citation_number)}")
            logger.debug(f"citation: {citation}")
            if cited_message_idx == int(citation_number):
                url = citation.get("metadata", {}).get("url", "")
                if ((BOT_MODE_ENABLED == False) or (
                        BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_BING_REFERENCE_OUTPUT == True)):
                    return f"[[{citation_number}]({url})]"
                else:
                    return ""
        # return match.group(0)  # 如果没有找到对应的引用，返回原文本
        logger.critical(f"没有找到对应的引用，舍弃{match.group(0)}引用")
        return ""

    # 使用 finditer 找到第一个匹配项
    match_iter = re.finditer(r'\u3010(\d+)\u2020(source|\u6765\u6e90)\u3011', text)
    first_match = next(match_iter, None)

    if first_match:
        start, end = first_match.span()
        replaced_text = text[:start] + replace_match(first_match) + text[end:]
        remaining_text = text[end:]
    else:
        replaced_text = text
        remaining_text = ""

    is_potential_citation = is_valid_citation_format(remaining_text)

    # 替换掉replaced_text末尾的remaining_text

    logger.debug(f"replaced_text: {replaced_text}")
    logger.debug(f"remaining_text: {remaining_text}")
    logger.debug(f"is_potential_citation: {is_potential_citation}")
    if is_potential_citation:
        replaced_text = replaced_text[:-len(remaining_text)]

    return replaced_text, remaining_text, is_potential_citation


def is_valid_sandbox_combined_corrected_final_v2(text):
    # 更新正则表达式以包含所有合法格式
    patterns = [
        r'.*\(sandbox:\/[^)]*\)?',  # sandbox 后跟路径，包括不完整路径
        r'.*\(',  # 只有 "(" 也视为合法格式
        r'.*\(sandbox(:|$)',  # 匹配 "(sandbox" 或 "(sandbox:"，确保后面不跟其他字符或字符串结束
        r'.*\(sandbox:.*\n*',  # 匹配 "(sandbox:" 后跟任意数量的换行符
    ]

    # 检查文本是否符合任一合法格式
    return any(bool(re.fullmatch(pattern, text)) for pattern in patterns)


def is_complete_sandbox_format(text):
    # 完整格式应该类似于 (sandbox:/xx/xx/xx 或 (sandbox:/xx/xx)
    pattern = r'.*\(sandbox\:\/[^)]+\)\n*'  # 匹配 "(sandbox:" 后跟任意数量的换行符
    return bool(re.fullmatch(pattern, text))


import urllib.parse
from urllib.parse import unquote


def replace_sandbox(text, conversation_id, message_id, api_key, proxy_api_prefix):
    def replace_match(match):
        sandbox_path = match.group(1)
        download_url = get_download_url(conversation_id, message_id, sandbox_path)
        if download_url == None:
            return "\n```\nError: 沙箱文件下载失败，这可能是因为您启用了隐私模式\n```"
        file_name = extract_filename(download_url)
        timestamped_file_name = timestamp_filename(file_name)
        if USE_OAIUSERCONTENT_URL == False:
            download_file(download_url, timestamped_file_name)
            return f"({UPLOAD_BASE_URL}/files/{timestamped_file_name})"
        else:
            return f"({download_url})"

    def get_download_url(conversation_id, message_id, sandbox_path):
        # 模拟发起请求以获取下载 URL
        sandbox_info_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/conversation/{conversation_id}/interpreter/download?message_id={message_id}&sandbox_path={sandbox_path}"

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        response = requests.get(sandbox_info_url, headers=headers)

        if response.status_code == 200:
            logger.debug(f"获取下载 URL 成功: {response.json()}")
            return response.json().get("download_url")
        else:
            logger.error(f"获取下载 URL 失败: {response.text}")
            return None

    def extract_filename(url):
        # 从 URL 中提取 filename 参数
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        filename = query_params.get("rscd", [""])[0].split("filename=")[-1]
        return filename

    def timestamp_filename(filename):
        # 在文件名前加上当前时间戳
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        # 解码URL编码的filename
        decoded_filename = unquote(filename)

        return f"{timestamp}_{decoded_filename}"

    def download_file(download_url, filename):
        # 下载并保存文件
        # 确保 ./files 目录存在
        if not os.path.exists("./files"):
            os.makedirs("./files")
        file_path = f"./files/{filename}"
        with requests.get(download_url, stream=True) as r:
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    # 替换 (sandbox:xxx) 格式的文本
    replaced_text = re.sub(r'\(sandbox:([^)]+)\)', replace_match, text)
    return replaced_text


def data_fetcher(upstream_response, data_queue, stop_event, last_data_time, api_key, chat_message_id, model,
                 proxy_api_prefix):
    all_new_text = ""

    first_output = True

    # 当前时间戳
    timestamp = int(time.time())

    buffer = ""
    last_full_text = ""  # 用于存储之前所有出现过的 parts 组成的完整文本
    last_full_code = ""
    last_full_code_result = ""
    last_content_type = None  # 用于记录上一个消息的内容类型
    conversation_id = ''
    citation_buffer = ""
    citation_accumulating = False
    file_output_buffer = ""
    file_output_accumulating = False
    execution_output_image_url_buffer = ""
    execution_output_image_id_buffer = ""
    message = None
    try:
        for chunk in upstream_response.iter_content(chunk_size=1024):
            if stop_event.is_set():
                logger.info(f"接受到停止信号，停止数据处理线程")
                break
            if chunk:
                buffer += chunk.decode('utf-8')
                # 检查是否存在 "event: ping"，如果存在，则只保留 "data:" 后面的内容
                if "event: ping" in buffer:
                    if "data:" in buffer:
                        buffer = buffer.split("data:", 1)[1]
                        buffer = "data:" + buffer
                # 使用正则表达式移除特定格式的字符串
                # print("应用正则表达式之前的 buffer:", buffer.replace('\n', '\\n'))
                buffer = re.sub(r'data: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}(\r\n|\r|\n){2}', '', buffer)
                # print("应用正则表达式之后的 buffer:", buffer.replace('\n', '\\n'))

                while 'data:' in buffer and '\n\n' in buffer:
                    end_index = buffer.index('\n\n') + 2
                    complete_data, buffer = buffer[:end_index], buffer[end_index:]
                    try:
                        data_content = complete_data.replace('data: ', '').strip()
                        if not data_content:
                            continue
                        data_json = json.loads(data_content)
                        # print(f"data_json: {data_json}")
                        message = data_json.get("message", {})

                        if message == {} or message == None:
                            logger.debug(f"message 为空: data_json: {data_json}")

                        message_id = message.get("id")
                        message_status = message.get("status")
                        content = message.get("content", {})
                        role = message.get("author", {}).get("role")
                        content_type = content.get("content_type")

                        metadata = {}
                        citations = []
                        try:
                            metadata = message.get("metadata", {})
                            citations = metadata.get("citations", [])
                        except:
                            pass
                        name = message.get("author", {}).get("name")
                        if (
                                role == "user" or message_status == "finished_successfully" or role == "system") and role != "tool":
                            # 如果是用户发来的消息，直接舍弃
                            continue
                        try:
                            conversation_id = data_json.get("conversation_id")
                            # print(f"conversation_id: {conversation_id}")
                            if conversation_id:
                                data_queue.put(('conversation_id', conversation_id))
                        except:
                            pass
                            # 只获取新的部分
                        new_text = ""
                        is_img_message = False
                        parts = content.get("parts", [])
                        for part in parts:
                            try:
                                # print(f"part: {part}")
                                # print(f"part type: {part.get('content_type')}")
                                if part.get('content_type') == 'image_asset_pointer':
                                    logger.debug(f"find img message~")
                                    is_img_message = True
                                    asset_pointer = part.get('asset_pointer').replace('file-service://', '')
                                    logger.debug(f"asset_pointer: {asset_pointer}")
                                    image_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files/{asset_pointer}/download"

                                    headers = {
                                        "Authorization": f"Bearer {api_key}"
                                    }
                                    image_response = requests.get(image_url, headers=headers)

                                    if image_response.status_code == 200:
                                        download_url = image_response.json().get('download_url')
                                        logger.debug(f"download_url: {download_url}")
                                        if USE_OAIUSERCONTENT_URL == True:
                                            if ((BOT_MODE_ENABLED == False) or (
                                                    BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT == True)):
                                                new_text = f"\n![image]({download_url})\n[下载链接]({download_url})\n"
                                            if BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT == True:
                                                if all_new_text != "":
                                                    new_text = f"\n图片链接：{download_url}\n"
                                                else:
                                                    new_text = f"图片链接：{download_url}\n"
                                        else:
                                            # 从URL下载图片
                                            # image_data = requests.get(download_url).content
                                            image_download_response = requests.get(download_url)
                                            # print(f"image_download_response: {image_download_response.text}")
                                            if image_download_response.status_code == 200:
                                                logger.debug(f"下载图片成功")
                                                image_data = image_download_response.content
                                                today_image_url = save_image(image_data)  # 保存图片，并获取文件名
                                                if ((BOT_MODE_ENABLED == False) or (
                                                        BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT == True)):
                                                    new_text = f"\n![image]({UPLOAD_BASE_URL}/{today_image_url})\n[下载链接]({UPLOAD_BASE_URL}/{today_image_url})\n"
                                                if BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT == True:
                                                    if all_new_text != "":
                                                        new_text = f"\n图片链接：{UPLOAD_BASE_URL}/{today_image_url}\n"
                                                    else:
                                                        new_text = f"图片链接：{UPLOAD_BASE_URL}/{today_image_url}\n"
                                            else:
                                                logger.error(f"下载图片失败: {image_download_response.text}")
                                        if last_content_type == "code":
                                            if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                                new_text = new_text
                                            else:
                                                new_text = "\n```\n" + new_text

                                        logger.debug(f"new_text: {new_text}")
                                        is_img_message = True
                                    else:
                                        logger.error(f"获取图片下载链接失败: {image_response.text}")
                            except:
                                pass

                        if is_img_message == False:
                            # print(f"data_json: {data_json}")
                            if content_type == "multimodal_text" and last_content_type == "code":
                                new_text = "\n```\n" + content.get("text", "")
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = content.get("text", "")
                            elif role == "tool" and name == "dalle.text2im":
                                logger.debug(f"无视消息: {content.get('text', '')}")
                                continue
                            # 代码块特殊处理
                            if content_type == "code" and last_content_type != "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = "\n```\n" + full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = full_code  # 更新完整代码以备下次比较
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = ""

                            elif last_content_type == "code" and content_type != "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = "\n```\n" + full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = ""  # 更新完整代码以备下次比较
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = ""

                            elif content_type == "code" and last_content_type == "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = full_code  # 更新完整代码以备下次比较
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = ""

                            else:
                                # 只获取新的 parts
                                parts = content.get("parts", [])
                                full_text = ''.join(parts)
                                if full_text == "![":
                                    last_full_text = "!"
                                new_text = full_text[len(last_full_text):]
                                last_full_text = full_text
                                if "\u3010" in new_text and not citation_accumulating:
                                    citation_accumulating = True
                                    citation_buffer = citation_buffer + new_text
                                    # print(f"开始积累引用: {citation_buffer}")
                                elif citation_accumulating:
                                    citation_buffer += new_text
                                    # print(f"积累引用: {citation_buffer}")
                                if citation_accumulating:
                                    if is_valid_citation_format(citation_buffer):
                                        # print(f"合法格式: {citation_buffer}")
                                        # 继续积累
                                        if is_complete_citation_format(citation_buffer):

                                            # 替换完整的引用格式
                                            replaced_text, remaining_text, is_potential_citation = replace_complete_citation(
                                                citation_buffer, citations)
                                            # print(replaced_text)  # 输出替换后的文本
                                            new_text = replaced_text

                                            if (is_potential_citation):
                                                citation_buffer = remaining_text
                                            else:
                                                citation_accumulating = False
                                                citation_buffer = ""
                                            # print(f"替换完整的引用格式: {new_text}")
                                        else:
                                            continue
                                    else:
                                        # 不是合法格式，放弃积累并响应
                                        # print(f"不合法格式: {citation_buffer}")
                                        new_text = citation_buffer
                                        citation_accumulating = False
                                        citation_buffer = ""

                                if "(" in new_text and not file_output_accumulating and not citation_accumulating:
                                    file_output_accumulating = True
                                    file_output_buffer = file_output_buffer + new_text
                                    logger.debug(f"开始积累文件输出: {file_output_buffer}")
                                elif file_output_accumulating:
                                    file_output_buffer += new_text
                                    logger.debug(f"积累文件输出: {file_output_buffer}")
                                if file_output_accumulating:
                                    if is_valid_sandbox_combined_corrected_final_v2(file_output_buffer):
                                        logger.debug(f"合法文件输出格式: {file_output_buffer}")
                                        # 继续积累
                                        if is_complete_sandbox_format(file_output_buffer):
                                            # 替换完整的引用格式
                                            replaced_text = replace_sandbox(file_output_buffer, conversation_id,
                                                                            message_id, api_key, proxy_api_prefix)
                                            # print(replaced_text)  # 输出替换后的文本
                                            new_text = replaced_text
                                            file_output_accumulating = False
                                            file_output_buffer = ""
                                            logger.debug(f"替换完整的文件输出格式: {new_text}")
                                        else:
                                            continue
                                    else:
                                        # 不是合法格式，放弃积累并响应
                                        logger.debug(f"不合法格式: {file_output_buffer}")
                                        new_text = file_output_buffer
                                        file_output_accumulating = False
                                        file_output_buffer = ""

                            # Python 工具执行输出特殊处理
                            if role == "tool" and name == "python" and last_content_type != "execution_output" and content_type != None:
                                full_code_result = ''.join(content.get("text", ""))
                                new_text = "`Result:` \n```\n" + full_code_result[len(last_full_code_result):]
                                if last_content_type == "code":
                                    if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                        new_text = ""
                                    else:
                                        new_text = "\n```\n" + new_text
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = full_code_result  # 更新完整代码以备下次比较
                            elif last_content_type == "execution_output" and (
                                    role != "tool" or name != "python") and content_type != None:
                                # new_text = content.get("text", "") + "\n```"
                                full_code_result = ''.join(content.get("text", ""))
                                new_text = full_code_result[len(last_full_code_result):] + "\n```\n"
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = ""
                                tmp_new_text = new_text
                                if execution_output_image_url_buffer != "":
                                    if ((BOT_MODE_ENABLED == False) or (
                                            BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT == True)):
                                        logger.debug(f"BOT_MODE_ENABLED: {BOT_MODE_ENABLED}")
                                        logger.debug(
                                            f"BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT: {BOT_MODE_ENABLED_MARKDOWN_IMAGE_OUTPUT}")
                                        new_text = tmp_new_text + f"![image]({execution_output_image_url_buffer})\n[下载链接]({execution_output_image_url_buffer})\n"
                                    if BOT_MODE_ENABLED == True and BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT == True:
                                        logger.debug(f"BOT_MODE_ENABLED: {BOT_MODE_ENABLED}")
                                        logger.debug(
                                            f"BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT: {BOT_MODE_ENABLED_PLAIN_IMAGE_URL_OUTPUT}")
                                        new_text = tmp_new_text + f"图片链接：{execution_output_image_url_buffer}\n"
                                    execution_output_image_url_buffer = ""

                                if content_type == "code":
                                    new_text = new_text + "\n```\n"
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = ""  # 更新完整代码以备下次比较
                            elif last_content_type == "execution_output" and role == "tool" and name == "python" and content_type != None:
                                full_code_result = ''.join(content.get("text", ""))
                                if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                                    new_text = ""
                                else:
                                    new_text = full_code_result[len(last_full_code_result):]
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = full_code_result

                            # 其余Action执行输出特殊处理
                            # if role == "tool" and name != "python" and name != "dalle.text2im" and last_content_type != "execution_output" and content_type != None:
                            #     new_text = ""
                            #     if last_content_type == "code":
                            #         if BOT_MODE_ENABLED and BOT_MODE_ENABLED_CODE_BLOCK_OUTPUT == False:
                            #             new_text = ""
                            #         else:
                            #             new_text = "\n```\n" + new_text

                        # 检查 new_text 中是否包含 <<ImageDisplayed>>
                        if "<<ImageDisplayed>>" in last_full_code_result:
                            # 进行提取操作
                            aggregate_result = message.get("metadata", {}).get("aggregate_result", {})
                            if aggregate_result:
                                messages = aggregate_result.get("messages", [])
                                for msg in messages:
                                    if msg.get("message_type") == "image":
                                        image_url = msg.get("image_url")
                                        if image_url:
                                            # 从 image_url 提取所需的字段
                                            image_file_id = image_url.split('://')[-1]
                                            logger.info(f"提取到的图片文件ID: {image_file_id}")
                                            if image_file_id != execution_output_image_id_buffer:
                                                image_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files/{image_file_id}/download"

                                                headers = {
                                                    "Authorization": f"Bearer {api_key}"
                                                }
                                                image_response = requests.get(image_url, headers=headers)

                                                if image_response.status_code == 200:
                                                    download_url = image_response.json().get('download_url')
                                                    logger.debug(f"download_url: {download_url}")
                                                    if USE_OAIUSERCONTENT_URL == True:
                                                        execution_output_image_url_buffer = download_url

                                                    else:
                                                        # 从URL下载图片
                                                        # image_data = requests.get(download_url).content
                                                        image_download_response = requests.get(download_url)
                                                        # print(f"image_download_response: {image_download_response.text}")
                                                        if image_download_response.status_code == 200:
                                                            logger.debug(f"下载图片成功")
                                                            image_data = image_download_response.content
                                                            today_image_url = save_image(image_data)  # 保存图片，并获取文件名
                                                            execution_output_image_url_buffer = f"{UPLOAD_BASE_URL}/{today_image_url}"

                                                        else:
                                                            logger.error(
                                                                f"下载图片失败: {image_download_response.text}")

                                            execution_output_image_id_buffer = image_file_id

                        # 从 new_text 中移除 <<ImageDisplayed>>
                        new_text = new_text.replace(
                            "All the files uploaded by the user have been fully loaded. Searching won't provide "
                            "additional information.",
                            UPLOAD_SUCCESS_TEXT)
                        new_text = new_text.replace("<<ImageDisplayed>>", "图片生成中，请稍后\n")

                        # print(f"收到数据: {data_json}")
                        # print(f"收到的完整文本: {full_text}")
                        # print(f"上次收到的完整文本: {last_full_text}")
                        # print(f"新的文本: {new_text}")

                        # 更新 last_content_type
                        if content_type != None:
                            last_content_type = content_type if role != "user" else last_content_type

                        model_slug = message.get("metadata", {}).get("model_slug") or model

                        if first_output:
                            new_data = {
                                "id": chat_message_id,
                                "object": "chat.completion.chunk",
                                "created": timestamp,
                                "model": model_slug,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"role": "assistant"},
                                        "finish_reason": None
                                    }
                                ]
                            }
                            q_data = 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                            data_queue.put(q_data)
                            first_output = False

                        new_data = {
                            "id": chat_message_id,
                            "object": "chat.completion.chunk",
                            "created": timestamp,
                            "model": model_slug,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": ''.join(new_text)
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }
                        # print(f"Role: {role}")
                        logger.info(f"发送消息: {new_text}")
                        tmp = 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                        # print(f"发送数据: {tmp}")
                        # 累积 new_text
                        all_new_text += new_text
                        q_data = 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                        data_queue.put(q_data)
                        last_data_time[0] = time.time()
                        if stop_event.is_set():
                            break
                    except json.JSONDecodeError:
                        # print("JSON 解析错误")
                        logger.info(f"发送数据: {complete_data}")
                        if complete_data == 'data: [DONE]\n\n':
                            logger.info(f"会话结束")
                            q_data = complete_data
                            data_queue.put(('all_new_text', all_new_text))
                            data_queue.put(q_data)
                            last_data_time[0] = time.time()
                            if stop_event.is_set():
                                break
        if citation_buffer != "":
            new_data = {
                "id": chat_message_id,
                "object": "chat.completion.chunk",
                "created": timestamp,
                "model": message.get("metadata", {}).get("model_slug"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": ''.join(citation_buffer)
                        },
                        "finish_reason": None
                    }
                ]
            }
            tmp = 'data: ' + json.dumps(new_data) + '\n\n'
            # print(f"发送数据: {tmp}")
            # 累积 new_text
            all_new_text += citation_buffer
            q_data = 'data: ' + json.dumps(new_data) + '\n\n'
            data_queue.put(q_data)
            last_data_time[0] = time.time()
        if buffer:
            try:
                buffer_json = json.loads(buffer)
                logger.info(f"最后的缓存数据: {buffer_json}")
                error_message = buffer_json.get("detail", {}).get("message", "未知错误")
                error_data = {
                    "id": chat_message_id,
                    "object": "chat.completion.chunk",
                    "created": timestamp,
                    "model": "error",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": ''.join("```\n" + error_message + "\n```")
                            },
                            "finish_reason": None
                        }
                    ]
                }
                tmp = 'data: ' + json.dumps(error_data) + '\n\n'
                logger.info(f"发送最后的数据: {tmp}")
                # 累积 new_text
                all_new_text += ''.join("```\n" + error_message + "\n```")
                q_data = 'data: ' + json.dumps(error_data) + '\n\n'
                data_queue.put(q_data)
                last_data_time[0] = time.time()
                complete_data = 'data: [DONE]\n\n'
                logger.info(f"会话结束")
                q_data = complete_data
                data_queue.put(('all_new_text', all_new_text))
                data_queue.put(q_data)
                last_data_time[0] = time.time()
            except:
                # print("JSON 解析错误")
                logger.info(f"发送最后的数据: {buffer}")
                error_data = {
                    "id": chat_message_id,
                    "object": "chat.completion.chunk",
                    "created": timestamp,
                    "model": "error",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": ''.join("```\n" + buffer + "\n```")
                            },
                            "finish_reason": None
                        }
                    ]
                }
                tmp = 'data: ' + json.dumps(error_data) + '\n\n'
                q_data = tmp
                data_queue.put(q_data)
                last_data_time[0] = time.time()
                complete_data = 'data: [DONE]\n\n'
                logger.info(f"会话结束")
                q_data = complete_data
                data_queue.put(('all_new_text', all_new_text))
                data_queue.put(q_data)
                last_data_time[0] = time.time()
    except Exception as e:
        logger.error(f"Exception: {e}")
        complete_data = 'data: [DONE]\n\n'
        logger.info(f"会话结束")
        q_data = complete_data
        data_queue.put(('all_new_text', all_new_text))
        data_queue.put(q_data)
        last_data_time[0] = time.time()


def keep_alive(last_data_time, stop_event, queue, model, chat_message_id):
    while not stop_event.is_set():
        if time.time() - last_data_time[0] >= 1:
            # logger.debug(f"发送保活消息")
            # 当前时间戳
            timestamp = int(time.time())
            new_data = {
                "id": chat_message_id,
                "object": "chat.completion.chunk",
                "created": timestamp,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": ''
                        },
                        "finish_reason": None
                    }
                ]
            }
            queue.put(f'data: {json.dumps(new_data)}\n\n')  # 发送保活消息
            last_data_time[0] = time.time()
        time.sleep(1)

    if stop_event.is_set():
        logger.debug(f"接受到停止信号，停止保活线程")
        return


import tiktoken


def count_tokens(text, model_name):
    """
    Count the number of tokens for a given text using a specified model.

    :param text: The text to be tokenized.
    :param model_name: The name of the model to use for tokenization.
    :return: Number of tokens in the text for the specified model.
    """
    # 获取指定模型的编码器
    if model_name == 'gpt-3.5-turbo':
        model_name = 'gpt-3.5-turbo'
    else:
        model_name = 'gpt-4'
    encoder = tiktoken.encoding_for_model(model_name)

    # 编码文本并计算token数量
    token_list = encoder.encode(text)
    return len(token_list)


def count_total_input_words(messages, model):
    """
    Count the total number of words in all messages' content.
    """
    total_words = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):  # 判断content是否为列表
            for item in content:
                if item.get("type") == "text":  # 仅处理类型为"text"的项
                    text_content = item.get("text", "")
                    total_words += count_tokens(text_content, model)
        elif isinstance(content, str):  # 处理字符串类型的content
            total_words += count_tokens(content, model)
        # 不处理其他类型的content

    return total_words


# 添加缓存
def add_to_dict(key, value):
    global refresh_dict
    refresh_dict[key] = value
    logger.info("添加access_token缓存成功.............")


import threading
import time


# 定义 Flask 路由
@app.route(f'/{API_PREFIX}/v1/chat/completions' if API_PREFIX else '/v1/chat/completions', methods=['POST'])
def chat_completions():
    logger.info(f"New Request")
    proxy_api_prefix = getPROXY_API_PREFIX(lock)

    if proxy_api_prefix == None:
        return jsonify({"error": "PROXY_API_PREFIX is not accessible"}), 401
    data = request.json
    messages = data.get('messages')
    model = data.get('model', "gpt-3.5-turbo")
    ori_model_name = model
    accessible_model_list = get_accessible_model_list()
    if model not in accessible_model_list and not 'gpt-4-gizmo-' in model:
        return jsonify({"error": "model is not accessible"}), 401
    model_config = find_model_config(model)
    if model_config:
        ori_model_name = model_config.get('ori_name', model)
    if "o1-" in ori_model_name:
        # 使用列表推导式过滤系统角色
        messages = [message for message in messages if message["role"] in ["user", "assistant"]]

    stream = data.get('stream', False)

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Authorization header is missing or invalid"}), 401
    api_key = None
    try:
        api_key = auth_header.split(' ')[1].split(',')[0].strip()
        account_id = auth_header.split(' ')[1].split(',')[1].strip()
        logging.info(f"{api_key}:{account_id}")
    except IndexError:
        account_id = None
    if not api_key.startswith("eyJhb"):
        refresh_token = api_key
        if api_key in refresh_dict:
            logger.info(f"从缓存读取到api_key.........。")
            api_key = refresh_dict.get(api_key)
        else:
            if REFRESH_TOACCESS_ENABLEOAI:
                api_key = oaiGetAccessToken(api_key)
            else:
                api_key = oaiFreeGetAccessToken(REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL, api_key)
            if not api_key.startswith("eyJhb"):
                return jsonify({"error": "refresh_token is wrong or refresh_token url is wrong!"}), 401
            add_to_dict(refresh_token, api_key)
    logger.info(f"api_key: {api_key}")

    upstream_response = send_text_prompt_and_get_response(messages, api_key, account_id, stream, model,
                                                          proxy_api_prefix)

    if upstream_response.status_code != 200:
        return jsonify({"error": f"{upstream_response.text}"}), upstream_response.status_code

    # 在非流式响应的情况下，我们需要一个变量来累积所有的 new_text
    all_new_text = ""

    # 处理流式响应
    def generate(proxy_api_prefix):
        nonlocal all_new_text  # 引用外部变量
        data_queue = Queue()
        stop_event = threading.Event()
        last_data_time = [time.time()]
        chat_message_id = generate_unique_id("chatcmpl")

        conversation_id_print_tag = False

        conversation_id = ''

        # 启动数据处理线程
        fetcher_thread = threading.Thread(target=data_fetcher, args=(
            upstream_response, data_queue, stop_event, last_data_time, api_key, chat_message_id, model,
            proxy_api_prefix))
        fetcher_thread.start()

        # 启动保活线程
        keep_alive_thread = threading.Thread(target=keep_alive,
                                             args=(last_data_time, stop_event, data_queue, model, chat_message_id))
        keep_alive_thread.start()

        try:
            while True:
                data = data_queue.get()
                if isinstance(data, tuple) and data[0] == 'all_new_text':
                    # 更新 all_new_text
                    logger.info(f"完整消息: {data[1]}")
                    all_new_text += data[1]
                elif isinstance(data, tuple) and data[0] == 'conversation_id':
                    if conversation_id_print_tag == False:
                        logger.info(f"当前会话id: {data[1]}")
                        conversation_id_print_tag = True
                    # 更新 conversation_id
                    conversation_id = data[1]
                    # print(f"收到会话id: {conversation_id}")
                elif data == 'data: [DONE]\n\n':
                    # 接收到结束信号，退出循环
                    timestamp = int(time.time())

                    new_data = {
                        "id": chat_message_id,
                        "object": "chat.completion.chunk",
                        "created": timestamp,
                        "model": model,
                        "choices": [
                            {
                                "delta": {},
                                "index": 0,
                                "finish_reason": "stop"
                            }
                        ]
                    }
                    q_data = 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                    yield q_data

                    logger.debug(f"会话结束-外层")
                    yield data
                    break
                else:
                    yield data

                # STEAM_SLEEP_TIME 优化传输质量，改善卡顿现象
                if stream and STEAM_SLEEP_TIME > 0:
                    time.sleep(STEAM_SLEEP_TIME)

        finally:
            stop_event.set()
            fetcher_thread.join()
            keep_alive_thread.join()

            # if conversation_id:
            #     # print(f"准备删除的会话id： {conversation_id}")
            #     delete_conversation(conversation_id, api_key,proxy_api_prefix)

    if not stream:
        # 执行流式响应的生成函数来累积 all_new_text
        # 迭代生成器对象以执行其内部逻辑
        for _ in generate(proxy_api_prefix):
            pass
        # 构造响应的 JSON 结构
        ori_model_name = ''
        model_config = find_model_config(model)
        if model_config:
            ori_model_name = model_config.get('ori_name', model)
        input_tokens = count_total_input_words(messages, ori_model_name)
        comp_tokens = count_tokens(all_new_text, ori_model_name)
        if input_tokens >= 100 and comp_tokens <= 0:
            # 返回错误消息和状态码429
            error_response = {"error": "空回复"}
            return jsonify(error_response), 429
        else:
            response_json = {
                "id": generate_unique_id("chatcmpl"),
                "object": "chat.completion",
                "created": int(time.time()),  # 使用当前时间戳
                "model": model,  # 使用请求中指定的模型
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": all_new_text  # 使用累积的文本
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    # 这里的 token 计数需要根据实际情况计算
                    "prompt_tokens": input_tokens,
                    "completion_tokens": comp_tokens,
                    "total_tokens": input_tokens + comp_tokens
                },
                "system_fingerprint": None
            }
            # 返回 JSON 响应
            return jsonify(response_json)
    else:
        return Response(generate(proxy_api_prefix), mimetype='text/event-stream')


@app.route(f'/{API_PREFIX}/v1/images/generations' if API_PREFIX else '/v1/images/generations', methods=['POST'])
def images_generations():
    logger.info(f"New Img Request")
    proxy_api_prefix = getPROXY_API_PREFIX(lock)
    if proxy_api_prefix == None:
        return jsonify({"error": "PROXY_API_PREFIX is not accessible"}), 401
    data = request.json
    logger.debug(f"data: {data}")
    api_key = None
    model = data.get('model', "gpt-3.5-turbo")
    ori_model_name = model
    accessible_model_list = get_accessible_model_list()
    if model not in accessible_model_list and not 'gpt-4-gizmo-' in model:
        return jsonify({"error": "model is not accessible"}), 401
    model_config = find_model_config(model)
    if model_config:
        ori_model_name = model_config.get('ori_name', model)
    if "o1-" in ori_model_name:
        # 使用列表推导式过滤系统角色
        messages = [message for message in messages if message["role"] in ["user", "assistant"]]
    # 获取请求中的response_format参数，默认为"url"
    response_format = data.get('response_format', 'url')
    # 获取请求中的size参数，默认为"1024x1024"
    response_size = data.get('size', '1024x1024')

    prompt = data.get('prompt', '')

    prompt = DALLE_PROMPT_PREFIX + '\nprompt:' + prompt + '\nsize:' + response_size

    # stream = data.get('stream', False)

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Authorization header is missing or invalid"}), 401
    try:
        api_key = auth_header.split(' ')[1].split(',')[0].strip()
        account_id = auth_header.split(' ')[1].split(',')[1].strip()
        logging.info(f"{api_key}:{account_id}")
    except IndexError:
        account_id = None
    if not api_key.startswith("eyJhb"):
        refresh_token = api_key
        if api_key in refresh_dict:
            logger.info(f"从缓存读取到api_key.........")
            api_key = refresh_dict.get(api_key)
        else:
            if REFRESH_TOACCESS_ENABLEOAI:
                api_key = oaiGetAccessToken(api_key)
            else:
                api_key = oaiFreeGetAccessToken(REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL, api_key)
            if not api_key.startswith("eyJhb"):
                return jsonify({"error": "refresh_token is wrong or refresh_token url is wrong!"}), 401
            add_to_dict(refresh_token, api_key)

    logger.info(f"api_key: {api_key}")

    image_urls = []

    messages = [
        {
            "role": "user",
            "content": prompt,
            "hasName": False
        }
    ]

    upstream_response = send_text_prompt_and_get_response(messages, api_key, account_id, False, model, proxy_api_prefix)

    if upstream_response.status_code != 200:
        return jsonify({"error": f"{upstream_response.text}"}), upstream_response.status_code

    # 在非流式响应的情况下，我们需要一个变量来累积所有的 new_text
    all_new_text = ""

    # 处理流式响应
    def generate(proxy_api_prefix):
        nonlocal all_new_text  # 引用外部变量
        chat_message_id = generate_unique_id("chatcmpl")
        # 当前时间戳
        timestamp = int(time.time())

        buffer = ""
        last_full_text = ""  # 用于存储之前所有出现过的 parts 组成的完整文本
        last_full_code = ""
        last_full_code_result = ""
        last_content_type = None  # 用于记录上一个消息的内容类型
        conversation_id = ''
        citation_buffer = ""
        citation_accumulating = False
        message = None
        for chunk in upstream_response.iter_content(chunk_size=1024):
            if chunk:
                buffer += chunk.decode('utf-8')
                # 检查是否存在 "event: ping"，如果存在，则只保留 "data:" 后面的内容
                if "event: ping" in buffer:
                    if "data:" in buffer:
                        buffer = buffer.split("data:", 1)[1]
                        buffer = "data:" + buffer
                # 使用正则表达式移除特定格式的字符串
                # print("应用正则表达式之前的 buffer:", buffer.replace('\n', '\\n'))
                buffer = re.sub(r'data: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}(\r\n|\r|\n){2}', '', buffer)
                # print("应用正则表达式之后的 buffer:", buffer.replace('\n', '\\n'))

                while 'data:' in buffer and '\n\n' in buffer:
                    end_index = buffer.index('\n\n') + 2
                    complete_data, buffer = buffer[:end_index], buffer[end_index:]
                    # 解析 data 块
                    try:
                        data_json = json.loads(complete_data.replace('data: ', ''))
                        # print(f"data_json: {data_json}")
                        message = data_json.get("message", {})

                        if message is None:
                            logger.error(f"message 为空: data_json: {data_json}")

                        message_status = message.get("status")
                        content = message.get("content", {})
                        role = message.get("author", {}).get("role")
                        content_type = content.get("content_type")
                        # logger.debug(f"content_type: {content_type}")
                        # logger.debug(f"last_content_type: {last_content_type}")

                        metadata = {}
                        citations = []
                        try:
                            metadata = message.get("metadata", {})
                            citations = metadata.get("citations", [])
                        except:
                            pass
                        name = message.get("author", {}).get("name")
                        if (
                                role == "user" or message_status == "finished_successfully" or role == "system") and role != "tool":
                            # 如果是用户发来的消息，直接舍弃
                            continue
                        try:
                            conversation_id = data_json.get("conversation_id")
                            logger.debug(f"conversation_id: {conversation_id}")
                        except:
                            pass
                            # 只获取新的部分
                        new_text = ""
                        is_img_message = False
                        parts = content.get("parts", [])
                        for part in parts:
                            try:
                                # print(f"part: {part}")
                                # print(f"part type: {part.get('content_type')}")
                                if part.get('content_type') == 'image_asset_pointer':
                                    logger.debug(f"find img message~")
                                    is_img_message = True
                                    asset_pointer = part.get('asset_pointer').replace('file-service://', '')
                                    logger.debug(f"asset_pointer: {asset_pointer}")
                                    image_url = f"{BASE_URL}{proxy_api_prefix}/backend-api/files/{asset_pointer}/download"

                                    headers = {
                                        "Authorization": f"Bearer {api_key}"
                                    }
                                    image_response = requests.get(image_url, headers=headers)

                                    if image_response.status_code == 200:
                                        download_url = image_response.json().get('download_url')
                                        logger.debug(f"download_url: {download_url}")
                                        if USE_OAIUSERCONTENT_URL == True and response_format == "url":
                                            image_link = f"{download_url}"
                                            image_urls.append(image_link)  # 将图片链接保存到列表中
                                            new_text = ""
                                        else:
                                            if response_format == "url":
                                                # 从URL下载图片
                                                # image_data = requests.get(download_url).content
                                                image_download_response = requests.get(download_url)
                                                # print(f"image_download_response: {image_download_response.text}")
                                                if image_download_response.status_code == 200:
                                                    logger.debug(f"下载图片成功")
                                                    image_data = image_download_response.content
                                                    today_image_url = save_image(image_data)  # 保存图片，并获取文件名
                                                    # new_text = f"\n![image]({UPLOAD_BASE_URL}/{today_image_url})\n[下载链接]({UPLOAD_BASE_URL}/{today_image_url})\n"
                                                    image_link = f"{UPLOAD_BASE_URL}/{today_image_url}"
                                                    image_urls.append(image_link)  # 将图片链接保存到列表中
                                                    new_text = ""
                                                else:
                                                    logger.error(f"下载图片失败: {image_download_response.text}")
                                            else:
                                                # 使用base64编码图片
                                                # image_data = requests.get(download_url).content
                                                image_download_response = requests.get(download_url)
                                                if image_download_response.status_code == 200:
                                                    logger.debug(f"下载图片成功")
                                                    image_data = image_download_response.content
                                                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                                                    image_urls.append(image_base64)
                                                    new_text = ""
                                                else:
                                                    logger.error(f"下载图片失败: {image_download_response.text}")
                                        if last_content_type == "code":
                                            new_text = new_text
                                            # new_text = "\n```\n" + new_text
                                        logger.debug(f"new_text: {new_text}")
                                        is_img_message = True
                                    else:
                                        logger.error(f"获取图片下载链接失败: {image_response.text}")
                            except:
                                pass

                        if is_img_message == False:
                            # print(f"data_json: {data_json}")
                            if content_type == "multimodal_text" and last_content_type == "code":
                                new_text = "\n```\n" + content.get("text", "")
                            elif role == "tool" and name == "dalle.text2im":
                                logger.debug(f"无视消息: {content.get('text', '')}")
                                continue
                            # 代码块特殊处理
                            if content_type == "code" and last_content_type != "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = "\n```\n" + full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = full_code  # 更新完整代码以备下次比较

                            elif last_content_type == "code" and content_type != "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = "\n```\n" + full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = ""  # 更新完整代码以备下次比较

                            elif content_type == "code" and last_content_type == "code" and content_type != None:
                                full_code = ''.join(content.get("text", ""))
                                new_text = full_code[len(last_full_code):]
                                # print(f"full_code: {full_code}")
                                # print(f"last_full_code: {last_full_code}")
                                # print(f"new_text: {new_text}")
                                last_full_code = full_code  # 更新完整代码以备下次比较

                            else:
                                # 只获取新的 parts
                                parts = content.get("parts", [])
                                full_text = ''.join(parts)
                                new_text = full_text[len(last_full_text):]
                                last_full_text = full_text  # 更新完整文本以备下次比较
                                if "\u3010" in new_text and not citation_accumulating:
                                    citation_accumulating = True
                                    citation_buffer = citation_buffer + new_text
                                    logger.debug(f"开始积累引用: {citation_buffer}")
                                elif citation_accumulating:
                                    citation_buffer += new_text
                                    logger.debug(f"积累引用: {citation_buffer}")
                                if citation_accumulating:
                                    if is_valid_citation_format(citation_buffer):
                                        logger.debug(f"合法格式: {citation_buffer}")
                                        # 继续积累
                                        if is_complete_citation_format(citation_buffer):

                                            # 替换完整的引用格式
                                            replaced_text, remaining_text, is_potential_citation = replace_complete_citation(
                                                citation_buffer, citations)
                                            # print(replaced_text)  # 输出替换后的文本
                                            new_text = replaced_text

                                            if (is_potential_citation):
                                                citation_buffer = remaining_text
                                            else:
                                                citation_accumulating = False
                                                citation_buffer = ""
                                            logger.debug(f"替换完整的引用格式: {new_text}")
                                        else:
                                            continue
                                    else:
                                        # 不是合法格式，放弃积累并响应
                                        logger.debug(f"不合法格式: {citation_buffer}")
                                        new_text = citation_buffer
                                        citation_accumulating = False
                                        citation_buffer = ""

                            # Python 工具执行输出特殊处理
                            if role == "tool" and name == "python" and last_content_type != "execution_output" and content_type != None:

                                full_code_result = ''.join(content.get("text", ""))
                                new_text = "`Result:` \n```\n" + full_code_result[len(last_full_code_result):]
                                if last_content_type == "code":
                                    new_text = "\n```\n" + new_text
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = full_code_result  # 更新完整代码以备下次比较
                            elif last_content_type == "execution_output" and (
                                    role != "tool" or name != "python") and content_type != None:
                                # new_text = content.get("text", "") + "\n```"
                                full_code_result = ''.join(content.get("text", ""))
                                new_text = full_code_result[len(last_full_code_result):] + "\n```\n"
                                if content_type == "code":
                                    new_text = new_text + "\n```\n"
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = ""  # 更新完整代码以备下次比较
                            elif last_content_type == "execution_output" and role == "tool" and name == "python" and content_type != None:
                                full_code_result = ''.join(content.get("text", ""))
                                new_text = full_code_result[len(last_full_code_result):]
                                # print(f"full_code_result: {full_code_result}")
                                # print(f"last_full_code_result: {last_full_code_result}")
                                # print(f"new_text: {new_text}")
                                last_full_code_result = full_code_result

                        # print(f"收到数据: {data_json}")
                        # print(f"收到的完整文本: {full_text}")
                        # print(f"上次收到的完整文本: {last_full_text}")
                        # print(f"新的文本: {new_text}")

                        # 更新 last_content_type
                        if content_type != None:
                            last_content_type = content_type if role != "user" else last_content_type

                        new_data = {
                            "id": chat_message_id,
                            "object": "chat.completion.chunk",
                            "created": timestamp,
                            "model": message.get("metadata", {}).get("model_slug"),
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": ''.join(new_text)
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }
                        # print(f"Role: {role}")
                        logger.info(f"发送消息: {new_text}")
                        tmp = 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                        # print(f"发送数据: {tmp}")
                        # 累积 new_text
                        all_new_text += new_text
                        yield 'data: ' + json.dumps(new_data, ensure_ascii=False) + '\n\n'
                    except json.JSONDecodeError:
                        # print("JSON 解析错误")
                        logger.info(f"发送数据: {complete_data}")
                        if complete_data == 'data: [DONE]\n\n':
                            logger.info(f"会话结束")
                            yield complete_data
        if citation_buffer != "":
            new_data = {
                "id": chat_message_id,
                "object": "chat.completion.chunk",
                "created": timestamp,
                "model": message.get("metadata", {}).get("model_slug"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": ''.join(citation_buffer)
                        },
                        "finish_reason": None
                    }
                ]
            }
            tmp = 'data: ' + json.dumps(new_data) + '\n\n'
            # print(f"发送数据: {tmp}")
            # 累积 new_text
            all_new_text += citation_buffer
            yield 'data: ' + json.dumps(new_data) + '\n\n'
        if buffer:
            # print(f"最后的数据: {buffer}")
            # delete_conversation(conversation_id, api_key)
            try:
                buffer_json = json.loads(buffer)
                error_message = buffer_json.get("detail", {}).get("message", "未知错误")
                error_data = {
                    "id": chat_message_id,
                    "object": "chat.completion.chunk",
                    "created": timestamp,
                    "model": "error",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": ''.join("```\n" + error_message + "\n```")
                            },
                            "finish_reason": None
                        }
                    ]
                }
                tmp = 'data: ' + json.dumps(error_data) + '\n\n'
                logger.info(f"发送最后的数据: {tmp}")
                # 累积 new_text
                all_new_text += ''.join("```\n" + error_message + "\n```")
                yield 'data: ' + json.dumps(error_data) + '\n\n'
            except:
                # print("JSON 解析错误")
                logger.info(f"发送最后的数据: {buffer}")
                yield buffer

        # delete_conversation(conversation_id, api_key)

    # 执行流式响应的生成函数来累积 all_new_text
    # 迭代生成器对象以执行其内部逻辑
    for _ in generate(proxy_api_prefix):
        pass
    # 构造响应的 JSON 结构
    response_json = {}
    # 检查 image_urls 是否为空
    if not image_urls:
        response_json = {
            "error": {
                "message": all_new_text,  # 使用累积的文本作为错误信息
                "type": "invalid_request_error",
                "param": "",
                "code": "content_policy_violation"
            }
        }
    else:
        if response_format == "url":
            response_json = {
                "created": int(time.time()),  # 使用当前时间戳
                # "reply": all_new_text,  # 使用累积的文本
                "data": [
                    {
                        "revised_prompt": all_new_text,  # 将描述文本加入每个字典
                        "url": url
                    } for url in image_urls
                ]  # 将图片链接列表转换为所需格式
            }
        else:
            response_json = {
                "created": int(time.time()),  # 使用当前时间戳
                # "reply": all_new_text,  # 使用累积的文本
                "data": [
                    {
                        "revised_prompt": all_new_text,  # 将描述文本加入每个字典
                        "b64_json": base64
                    } for base64 in image_urls
                ]  # 将图片链接列表转换为所需格式
            }
    logger.debug(f"response_json: {response_json}")

    # 返回 JSON 响应
    return jsonify(response_json)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


# 特殊的 OPTIONS 请求处理器
@app.route(f'/{API_PREFIX}/v1/chat/completions' if API_PREFIX else '/v1/chat/completions', methods=['OPTIONS'])
def options_handler():
    logger.info(f"Options Request")
    return Response(status=200)


@app.route('/', defaults={'path': ''}, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
@app.route('/<path:path>', methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
def catch_all(path):
    logger.debug(f"未知请求: {path}")
    logger.debug(f"请求方法: {request.method}")
    logger.debug(f"请求头: {request.headers}")
    logger.debug(f"请求体: {request.data}")

    html_string = f"""
        <!DOCTYPE html>
        <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Document</title>
            </head>
            <body>
                <p> Thanks for using RefreshToV1Api {VERSION}</p>
                <p> 感谢Ink-Osier大佬的付出，敬礼！！！</p>
                <p><a href="https://github.com/Yanyutin753/RefreshToV1Api">项目地址</a></p>
            </body>
        </html>
        """
    return html_string, 500


@app.route('/images/<filename>')
@cross_origin()  # 使用装饰器来允许跨域请求
def get_image(filename):
    # 检查文件是否存在
    if not os.path.isfile(os.path.join('images', filename)):
        return "文件不存在哦！", 404
    return send_from_directory('images', filename)


@app.route('/files/<filename>')
@cross_origin()  # 使用装饰器来允许跨域请求
def get_file(filename):
    # 检查文件是否存在
    if not os.path.isfile(os.path.join('files', filename)):
        return "文件不存在哦！", 404
    return send_from_directory('files', filename)


@app.route(f'/{API_PREFIX}/getAccountID' if API_PREFIX else '/getAccountID', methods=['POST'])
@cross_origin()  # 使用装饰器来允许跨域请求
def getAccountID():
    logger.info(f"New Account Request")
    proxy_api_prefix = getPROXY_API_PREFIX(lock)
    if proxy_api_prefix is None:
        return jsonify({"error": "PROXY_API_PREFIX is not accessible"}), 401
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Authorization header is missing or invalid"}), 401
    api_key = auth_header.split(' ')[1].split(',')[0].strip()

    if not api_key.startswith("eyJhb"):
        refresh_token = api_key
        if api_key in refresh_dict:
            logger.info(f"从缓存读取到api_key.........")
            api_key = refresh_dict.get(api_key)
        else:
            if REFRESH_TOACCESS_ENABLEOAI:
                api_key = oaiGetAccessToken(api_key)
            else:
                api_key = oaiFreeGetAccessToken(REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL, api_key)
            if not api_key.startswith("eyJhb"):
                return jsonify({"error": "refresh_token is wrong or refresh_token url is wrong!"}), 401
            add_to_dict(refresh_token, api_key)
    logger.info(f"api_key: {api_key}")

    url = f"{BASE_URL}{proxy_api_prefix}/backend-api/accounts/check/v4-2023-04-27"
    headers = {
        "Authorization": "Bearer " + api_key
    }
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json()
        result = {"plus": set(), "team": set()}
        for account_id, account_data in data["accounts"].items():
            plan_type = account_data["account"]["plan_type"]
            if plan_type == "team":
                result[plan_type].add(account_id)
            elif plan_type == "plus":
                result[plan_type].add(account_id)
        result = {plan_type: list(ids) for plan_type, ids in result.items()}
        return jsonify(result)
    else:
        return jsonify({"error": "Request failed."}), 400


# 内置自动刷新access_token
def updateRefresh_dict():
    success_num = 0
    error_num = 0
    logger.info(f"==========================================")
    logging.info("开始更新access_token.........")
    for key in refresh_dict:
        refresh_token = key
        if REFRESH_TOACCESS_ENABLEOAI:
            access_token = oaiGetAccessToken(key)
        else:
            access_token = oaiFreeGetAccessToken(REFRESH_TOACCESS_OAIFREE_REFRESHTOACCESS_URL, key)
        if not access_token.startswith("eyJhb"):
            logger.debug("refresh_token is wrong or refresh_token url is wrong!")
            error_num += 1
        add_to_dict(refresh_token, access_token)
        success_num += 1
    logging.info("更新成功: " + str(success_num) + ", 失败: " + str(error_num))
    logger.info(f"==========================================")
    logging.info("开始更新KEY_FOR_GPTS_INFO_ACCESS_TOKEN和GPTS配置信息.......")
    # 加载配置并添加到全局列表
    gpts_data = load_gpts_config("./data/gpts.json")
    add_config_to_global_list(BASE_URL, getPROXY_API_PREFIX(lock), gpts_data)

    accessible_model_list = get_accessible_model_list()
    logger.info(f"当前可用 GPTS 列表: {accessible_model_list}")

    # 检查列表中是否有重复的模型名称
    if len(accessible_model_list) != len(set(accessible_model_list)):
        raise Exception("检测到重复的模型名称，请检查环境变量或配置文件......")
    logging.info("更新KEY_FOR_GPTS_INFO_ACCESS_TOKEN和GPTS配置信息成功......")
    logger.info(f"==========================================")


# 每天3点自动刷新
scheduler.add_job(id='updateRefresh_run', func=updateRefresh_dict, trigger='cron', hour=3, minute=0)

# 运行 Flask 应用
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=33333, threaded=True)
