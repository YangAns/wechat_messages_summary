from loguru import logger
from openai import OpenAI
import datetime
import os
import re
import requests
from dotenv import load_dotenv, find_dotenv

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
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "").strip()

import subprocess

# Windows 专用：隐藏命令行窗口标志
CREATE_NO_WINDOW = 0x08000000


def get_weflow_headers():
    if not ACCESS_TOKEN:
        return {}
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


class WeChatNotifier:
    """微信 webhook 通知器"""

    def __init__(self, webhook_url: str, webhook_secret: str):
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret

    def send_message(self, text: str) -> bool:
        if not self.webhook_url or not self.webhook_secret:
            logger.warning("微信 Webhook 配置不完整，跳过通知")
            return False

        try:
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Secret": self.webhook_secret,
            }
            payload = {"text": text}
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("微信通知发送成功")
                return True
            logger.error(f"微信通知发送失败: HTTP {response.status_code} - {response.text}")
            return False
        except requests.exceptions.Timeout:
            logger.error("微信通知发送超时")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"微信通知发送失败: {e}")
            return False
        except Exception as e:
            logger.error(f"发送微信通知时发生错误: {e}")
            return False


def build_wechat_summary_message(group_name, summary, trigger_mode, start_dt=None, end_dt=None, saved_path=None,
                                 git_pushed=None):
    """构建微信通知内容"""
    trigger_text = "手动生成" if trigger_mode == "manual" else "定时任务"
    lines = [f"✅ 群聊总结已生成", f"群聊: {group_name}", f"触发方式: {trigger_text}"]

    if start_dt and end_dt:
        lines.append(f"时间范围: {start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}")

    if git_pushed is True:
        lines.append("GitHub 推送: 成功")
    elif git_pushed is False:
        lines.append("GitHub 推送: 失败")

    full_content = (summary or "").replace("\r\n", "\n").replace("\r", "\n")
    full_content = re.sub(r"\n{3,}", "\n\n", full_content).strip()

    if full_content:
        lines.append("")
        lines.append("总结内容:")
        lines.append(full_content)

    return "\n".join(lines)


def send_summary_to_wechat(group_name, summary, webhook_url, webhook_secret, trigger_mode, start_dt=None, end_dt=None,
                           saved_path=None, git_pushed=None):
    """发送总结结果到微信 webhook"""
    if not webhook_url or not webhook_secret:
        logger.info("未配置微信 Webhook，跳过推送")
        return False

    message = build_wechat_summary_message(
        group_name=group_name,
        summary=summary,
        trigger_mode=trigger_mode,
        start_dt=start_dt,
        end_dt=end_dt,
        saved_path=saved_path,
        git_pushed=git_pushed,
    )
    notifier = WeChatNotifier(webhook_url, webhook_secret)
    return notifier.send_message(message)


def resolve_group_id(keyword):
    """通过关键字搜索获取群聊 ID (username)，要求群名完全匹配"""
    endpoint = f"{BASE_API_URL}/contacts"
    try:
        params = {"keyword": keyword}
        response = requests.get(endpoint, params=params, headers=get_weflow_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            # 根据 API 文档，联系人列表在 data["contacts"] 中
            contacts = data.get("contacts", [])
            if contacts:
                # 遍历结果，寻找完全匹配群名的群聊
                for contact in contacts:
                    username = contact.get("username", "")
                    display_name = contact.get("displayName", "")
                    # 条件：必须是群聊 (@chatroom) 且 群名 (displayName) 完全一致
                    if "@chatroom" in username and display_name == keyword:
                        logger.info(f"成功匹配群聊: {display_name} ({username})")
                        return username

                logger.warning(f"搜索到匹配项但未找到完全匹配的群聊: {keyword}")
        else:
            logger.error(f"搜索接口返回错误: {response.status_code}")
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
        response = requests.get(endpoint, params=params, headers=get_weflow_headers(), timeout=30)
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

    # 按照时间戳从小到大排序（升序），确保对话逻辑正常
    all_messages.sort(key=lambda x: x.get("timestamp", 0))

    logger.info(f"共拉取消息: {len(all_messages)} 条")
    return all_messages


def generate_ai_summary(messages, ai_config, prompt_template, my_nickname=None, start_dt=None, end_dt=None):
    """调用 AI 生成总结"""
    if not messages:
        return "未获取到任何消息内容。"

    if not ai_config:
        return "未配置 AI 服务。"

    candidate_names = set()
    if my_nickname and my_nickname.strip():
        candidate_names.add(my_nickname.strip())
    for msg in messages:
        group_nickname = (msg.get("groupNickName") or "").strip()
        if group_nickname:
            candidate_names.add(group_nickname)
    mention_tags = [f"@{name}" for name in candidate_names]
    candidate_names_text = "、".join(sorted(candidate_names))

    # 时间段信息标注
    time_info = ""
    if start_dt and end_dt:
        time_info = f"聊天时间范围：{start_dt.strftime('%Y-%m-%d %H:%M')} 至 {end_dt.strftime('%Y-%m-%d %H:%M')}\n\n"

    # 格式化消息为 [HH:mm] Sender: Content
    formatted_msgs = []
    mention_found = False  # 是否有提到我
    for msg in messages:
        sender = msg.get("accountName") or "未知"
        content = msg.get("content") or ""
        ts = msg.get("timestamp", 0)

        # 识别是否提到我（同时支持微信昵称和当前群昵称）
        is_mention_me = bool(content and any(tag in content for tag in mention_tags))
        if is_mention_me:
            mention_found = True

        # 将时间戳转换为 HH:mm 格式
        time_str = ""
        if ts > 0:
            dt = datetime.datetime.fromtimestamp(ts)
            time_str = f"[{dt.strftime('%H:%M')}] "

        if content.strip():
            # 如果提到我，在消息前显式标注 [提到我]
            prefix = "[提到我] " if is_mention_me else ""
            formatted_msgs.append(f"{time_str}{sender}: {prefix}{content}")

    if not formatted_msgs:
        return "未发现有效的文本消息。"

    messages_text = time_info + "\n".join(formatted_msgs)

    try:
        client = OpenAI(
            api_key=ai_config.get('api_key'),
            base_url=ai_config.get('base_url')
        )

        system_prompt = prompt_template
        # 硬性约束：严禁废话开场和结束
        system_prompt += "\n\n**硬性输出规则（严禁违反）：**\n1. 严禁输出任何开场白、确认词（如“好的”、“没问题”）、自我介绍或结语。\n2. 输出必须直接从正文或标题开始，首行必须是 Markdown 格式的报告标题。\n3. 严禁输出任何多余的废话内容。"

        if ai_config.get('use_markdown', True):
            system_prompt += "\n\n**要求**：请务必以 Markdown 格式输出，使用二级或三级标题、列表、表格以及加粗等语法，使报告呈现结构化美感。"

        # 如果有时间信息，在系统提示中也加入该信息，帮助 AI 建立时间感
        if time_info:
            system_prompt += f"\n\n注意：当前处理的对话发生在以下时间段：{time_info.strip()}"

        # 强化对提到我的消息关注（同时支持微信昵称和群昵称）
        if mention_found and candidate_names:
            # system_prompt += f"""
            #             \n\n**重要补充指令**：
            #             1. 本次聊天记录中有人 @了用户，这些消息在正文中已被标记为 '[提到我]'。
            #             2. 用户在本群中可能被称呼为：{candidate_names_text}。
            #             3. 请在输出文档的**最后部分（末尾）**，增加一个名为 '📌 与我相关 / 待办事项' 的专门章节。
            #             4. 在该章节中，详细列出谁在什么时间提到或询问了用户，具体内容是什么。
            #             5. 如果该消息暗示了需要用户执行的任务，请以待办列表的形式清晰呈现。
            #         """
            system_prompt += f"""
                              \n\n**重要补充指令**：
                              1. 本次聊天记录中有人 @了用户，这些消息在正文中已被标记为 '[提到我]'。
                              2. 用户在本群中可能被称呼为：{candidate_names_text}。
                          """
        elif not candidate_names:
            system_prompt += "\n\n提示：总结时请保持客观中立的视角。由于未配置特定用户身份，无需生成 '与我相关' 的专项章节。"
        else:
            system_prompt += f"\n\n注意：用户在本群中可能被称呼为：{candidate_names_text}。虽然本次对话中没有直接提及这些称呼，但仍请留意是否有与该用户职责或关注点相关的隐含内容。"

        completion = client.chat.completions.create(
            model=ai_config.get('model', 'qwen-plus'),
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"以下是微信群聊天记录：\n\n{messages_text}"}
            ]
        )
        result = completion.choices[0].message.content

        # 后处理：将候选昵称统一替换为“我”，增强第一视角感
        if result:
            for name in sorted(candidate_names, key=len, reverse=True):
                result = re.sub(rf'(?<!\w){re.escape(name)}(?!\w)', '\u6211', result)

        return result
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
        # timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
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
            subprocess.run(["git", "init"], cwd=summary_root, check=True, capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=summary_root, check=True,
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=summary_root, check=True,
                           capture_output=True, creationflags=CREATE_NO_WINDOW)

        # 拉取最新代码 (Pull)
        try:
            pull_cmd = ["git", "-c", extra_header, "pull", "origin", branch, "--rebase"]
            subprocess.run(pull_cmd, cwd=summary_root, check=True, capture_output=True, creationflags=CREATE_NO_WINDOW)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Git Pull 失败 (可能是新仓库): {e.stderr.decode() if e.stderr else str(e)}")

        # 执行推送流程
        subprocess.run(["git", "add", rel_file_path], cwd=summary_root, check=True, capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
        subprocess.run(["git", "commit", "-m", f"Auto summary: {rel_file_path}"], cwd=summary_root, check=True,
                       capture_output=True, creationflags=CREATE_NO_WINDOW)

        # 尝试切换或创建分支
        subprocess.run(["git", "checkout", "-B", branch], cwd=summary_root, check=True, capture_output=True,
                       creationflags=CREATE_NO_WINDOW)

        # 推送 (Push)
        push_cmd = ["git", "-c", extra_header, "push", "-u", "origin", branch]
        subprocess.run(push_cmd, cwd=summary_root, check=True, capture_output=True, creationflags=CREATE_NO_WINDOW)

        logger.info(f"GitHub 推送成功: {rel_file_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git 命令执行失败: {e.stderr.decode() if e.stderr else str(e)}")
        return False
    except Exception as e:
        logger.error(f"GitHub 推送异常: {e}")
        return False


def auto_scheduled_task(group_name, duration_hours, ai_config, prompt_template, git_config=None, my_nickname=None,
                        wechat_config=None):
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

    summary = generate_ai_summary(messages, ai_config, prompt_template, my_nickname=my_nickname, start_dt=start_time,
                                  end_dt=end_time)

    # 保存文件，格式为 summary/群聊名称/群聊名称聊天总结_YYMMDDHHmmss.md
    # timestamp_str = end_time.strftime("%Y%m%d%H%M%S")
    timestamp_str = end_time.strftime("%Y%m%d")
    safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 在文件名中包含群聊名称文件夹
    filename = os.path.join(current_dir, "summary", safe_name, f"{safe_name}聊天总结_{timestamp_str}.md")

    saved_path = save_summary_to_file(group_name, summary, filename)
    git_pushed = None

    if saved_path and git_config and git_config.get("enabled"):
        git_pushed = git_push_file(
            saved_path,
            git_config.get("repo"),
            git_config.get("token"),
            git_config.get("branch", "main")
        )

    if saved_path and wechat_config and wechat_config.get("enabled"):
        send_summary_to_wechat(
            group_name=group_name,
            summary=summary,
            webhook_url=wechat_config.get("webhook_url", ""),
            webhook_secret=wechat_config.get("webhook_secret", ""),
            trigger_mode="schedule",
            start_dt=start_time,
            end_dt=end_time,
            saved_path=saved_path,
            git_pushed=git_pushed,
        )

    logger.info(f"定时任务完成: {group_name}")


if __name__ == "__main__":
    # 模块作为主程序运行时的测试示例
    pass
