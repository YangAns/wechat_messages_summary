from loguru import logger
from openai import OpenAI
import time
import datetime
import os
import requests
from dotenv import load_dotenv,find_dotenv

# 加载 .env 配置
load_dotenv(find_dotenv(), override=True)

# 配置日志记录
logger.remove()
logger.add(
    "logs/wx_summary_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    encoding="utf-8",
    enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="INFO",
)

BASE_API_URL = os.environ["BASE_API_URL"]

import subprocess

def resolve_group_id(keyword):
    """通过关键字搜索获取群聊 ID (username)"""
    endpoint = f"{BASE_API_URL}/contacts"
    try:
        params = {"keyword": keyword}
        response = requests.get(endpoint, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # 根据 API 文档，联系人列表在 data["contacts"] 中
            contacts = data.get("contacts", [])
            if contacts and len(contacts) > 0:
                # 优先返回匹配的群聊 (@chatroom)
                for contact in contacts:
                    if "@chatroom" in contact.get("username", ""):
                        return contact.get("username")
                # 如果没找到群聊，返回第一个匹配项
                return contacts[0].get("username")
        logger.error(f"未找到群聊: {keyword}, 状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"搜索群聊异常: {e}")
    return None

def fetch_chat_messages(talker_id, start_ts, end_ts, limit=100, offset=0):
    """获取聊天记录，使用 chatlab 格式。返回消息列表"""
    endpoint = f"{BASE_API_URL}/messages"
    try:
        params = {
            "talker": talker_id,
            "start": int(start_ts),
            "end": int(end_ts),
            "format": "chatlab",
            "limit": limit,
            "offset": offset,
        }
        response = requests.get(endpoint, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("messages", [])
        logger.error(f"获取消息失败: {response.status_code}")
    except Exception as e:
        logger.error(f"获取消息异常:{e}")
    return []

def fetch_all_chat_messages(talker_id, start_ts, end_ts, page_size=1000):
    """循环分页拉取指定时间段内的全部消息，以实际返回条数判断是否还有更多"""
    all_messages = []
    offset = 0
    while True:
        messages = fetch_chat_messages(
            talker_id, start_ts, end_ts, limit=page_size, offset=offset
        )
        all_messages.extend(messages)
        if len(messages) < page_size:
            break
        offset += len(messages)
    logger.info(f"共拉取消息: {len(all_messages)} 条")
    return all_messages

def generate_ai_summary(messages, ai_config, prompt_template):
    """调用 AI 生成总结"""
    if not messages:
        return "未获取到任何消息内容。"

    if not ai_config:
        return "未配置 AI 服务。"

    # 格式化消息为 Sender: Content
    formatted_msgs = []
    for msg in messages:
        sender = msg.get("accountName") or "未知"
        content = msg.get("content") or ""
        if content.strip():
            formatted_msgs.append(f"{sender}: {content}")

    if not formatted_msgs:
        return "未发现有效的文本消息。"

    messages_text = "\n".join(formatted_msgs)

    try:
        client = OpenAI(
            api_key=ai_config.get('api_key'),
            base_url=ai_config.get('base_url')
        )

        system_prompt = prompt_template
        if ai_config.get('use_markdown', True):
            system_prompt += "\n\n**要求**：请务必以 Markdown 格式输出，使用二级或三级标题、列表、表格以及加粗等语法，使报告呈现结构化美感。"

        completion = client.chat.completions.create(
            model=ai_config.get('model', 'qwen-plus'),
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"以下是微信群聊天记录：\n\n{messages_text}"}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"AI 总结生成失败: {e}")
        return f"生成总结时出错: {e}"

def save_summary_to_file(group_name, summary, filename=None):
    """保存总结到本地文件，支持按群聊名称分类"""
    if not summary:
        return None

    # 获取当前文件所在目录的 summary 子目录
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 建立安全的文件名/目录名
    safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()

    # 构建目录结构: summary/群聊名称/
    summary_dir = os.path.join(current_dir, "summary", safe_name)

    if not os.path.exists(summary_dir):
        os.makedirs(summary_dir, exist_ok=True)

    if not filename:
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = os.path.join(summary_dir, f"{safe_name}聊天总结_{timestamp}.md")
    else:
        # 如果传入了 filename，确保它的父目录存在
        os.makedirs(os.path.dirname(filename), exist_ok=True)

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(summary)
        logger.info(f"总结已保存: {filename}")
        return filename
    except Exception as e:
        logger.error(f"保存总结失败: {e}")
        return None

def git_push_file(file_path, repo_url, token, branch="main"):
    """将文件推送到 GitHub 仓库"""
    try:
        # 始终在 summary 根目录进行 Git 操作
        current_dir = os.path.dirname(os.path.abspath(__file__))
        summary_root = os.path.join(current_dir, "summary")
        if not os.path.exists(summary_root):
            os.makedirs(summary_root, exist_ok=True)

        # 获取文件相对于 summary 根目录的路径
        rel_file_path = os.path.relpath(file_path, summary_root)

        # 准备认证信息
        import base64
        auth_str = base64.b64encode(f"oauth2:{token}".encode()).decode()
        extra_header = f"http.{repo_url}.extraHeader=Authorization: Basic {auth_str}"

        # 检查是否已经是 Git 仓库
        if not os.path.exists(os.path.join(summary_root, ".git")):
            subprocess.run(["git", "init"], cwd=summary_root, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=summary_root, check=True, capture_output=True)
        else:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=summary_root, check=True, capture_output=True)

        # 拉取最新代码 (Pull)
        try:
            pull_cmd = ["git", "-c", extra_header, "pull", "origin", branch, "--rebase"]
            subprocess.run(pull_cmd, cwd=summary_root, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Git Pull 失败 (可能是新仓库): {e.stderr.decode() if e.stderr else str(e)}")

        # 执行推送流程
        subprocess.run(["git", "add", rel_file_path], cwd=summary_root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Auto summary: {rel_file_path}"], cwd=summary_root, check=True, capture_output=True)

        # 尝试切换或创建分支
        subprocess.run(["git", "checkout", "-B", branch], cwd=summary_root, check=True, capture_output=True)

        # 推送 (Push)
        push_cmd = ["git", "-c", extra_header, "push", "-u", "origin", branch]
        subprocess.run(push_cmd, cwd=summary_root, check=True, capture_output=True)

        logger.info(f"GitHub 推送成功: {rel_file_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git 命令执行失败: {e.stderr.decode() if e.stderr else str(e)}")
        return False
    except Exception as e:
        logger.error(f"GitHub 推送异常: {e}")
        return False

def auto_scheduled_task(group_name, duration_hours, ai_config, prompt_template, git_config=None):
    """定时任务执行逻辑"""
    logger.info(f"开始执行定时任务: {group_name}")

    group_id = resolve_group_id(group_name)
    if not group_id:
        logger.error(f"定时任务失败: 无法解析群聊 ID {group_name}")
        return

    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(hours=duration_hours)

    messages = fetch_all_chat_messages(group_id, start_time.timestamp(), end_time.timestamp())
    if not messages:
        logger.info(f"定时任务: {group_name} 在指定时间内无消息")
        return

    summary = generate_ai_summary(messages, ai_config, prompt_template)

    # 保存文件，格式为 summary/群聊名称/群聊名称聊天总结_YYMMDDHHmmss.md
    timestamp_str = end_time.strftime("%Y%m%d%H%M%S")
    safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 在文件名中包含群聊名称文件夹
    filename = os.path.join(current_dir, "summary", safe_name, f"{safe_name}聊天总结_{timestamp_str}.md")

    saved_path = save_summary_to_file(group_name, summary, filename)

    if saved_path and git_config and git_config.get("enabled"):
        git_push_file(
            saved_path,
            git_config.get("repo"),
            git_config.get("token"),
            git_config.get("branch", "main")
        )

    logger.info(f"定时任务完成: {group_name}")

if __name__ == "__main__":
    msgs = fetch_chat_messages(talker_id="53725032966@chatroom", start_ts=1774683554, end_ts=1774769954, limit=1000)
    print(len(msgs))
