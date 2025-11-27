import os
import time

from flask import Flask, request, abort
from dotenv import load_dotenv

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from google import genai
from rag_utils import query_db

# 讀取 .env 中的環境變數（開發用）
load_dotenv()

app = Flask(__name__)

# --- 使用者狀態（暫存在記憶體） ---
# 請注意：程式重啟後資料會消失，正式環境建議用資料庫（Redis / MongoDB / Postgres 等）
user_profile: dict[str, dict] = {}

# --- 讀取環境變數 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("請先設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

if not GEMINI_API_KEY:
    raise ValueError("請先設定環境變數 GEMINI_API_KEY")

# --- 初始化 LINE 與 Gemini ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini client 全域共用（避免每次新建浪費時間）
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def ask_gemini_sport_assistant(user_text: str, profile: dict) -> str:
    """
    呼叫 Gemini，請他扮演「運動教練 + 營養師」，並根據使用者的基本資料回覆。

    參數：
        user_text: 使用者在 LINE 輸入的問題。
        profile:   該使用者的個人資料 dict，例如：
                   {"height": 170, "weight": 65.0, "goal": "減脂"}

    回傳：
        給使用者的建議文字（已經是繁體中文，含總結 + 3 個步驟）。
    """
    start = time.time()
    print("[Gemini] 開始呼叫, user_text =", user_text)

    profile_text = (
        "使用者資料：\n"
        f"- 身高：{profile.get('height', '未提供')} cm\n"
        f"- 體重：{profile.get('weight', '未提供')} kg\n"
        f"- 運動目標：{profile.get('goal', '未提供')}\n"
    )

    # RAG: 檢索相關資料
    relevant_docs = query_db(user_text)
    context_str = ""
    if relevant_docs:
        context_str = "\n參考資料（請優先參考以下資訊回答）：\n" + "\n".join(relevant_docs) + "\n"
        print(f"[RAG] 找到 {len(relevant_docs)} 筆相關資料")

    system_prompt = (
        "你是一位專業的運動教練與運動營養師，同時也是 Sport Line Gym 的客服助理。\n"
        "請根據以下規則回答問題：\n"
        "1. 回答語言使用繁體中文。\n"
        "2. **關於參考資料的使用**：\n"
        "   - 系統會提供「參考資料」。請優先檢查參考資料是否包含使用者問題的答案。\n"
        "   - **如果參考資料能回答問題**（例如詢問營業時間、費用、服務項目等），請用**自然、親切的口語**直接回答，**完全不要**使用「【建議】...【執行步驟】...」的格式。\n"
        "3. **關於一般運動建議**：\n"
        "   - 如果參考資料與問題無關，且使用者是在詢問運動訓練、飲食菜單等專業建議，請務必遵守以下固定格式：\n"
        "     【建議】：1~2 句重點說明。\n"
        "     【執行步驟】：列出 3 個具體、可執行的步驟，依序編號 1, 2, 3。\n"
        "4. 建議要務實，不要太誇張或極端，且簡短重點回答。\n"
        "5. 不要使用任何 Markdown 語法，尤其是不要在文字中使用 ** 或 * 來表示粗體或斜體。\n"
    )

    # 呼叫 Gemini 模型（使用較快的 gemini-2.5-flash）
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            system_prompt,
            context_str,  # 加入 RAG 上下文
            profile_text,
            f"使用者的問題：{user_text}",
        ],
    )

    elapsed = time.time() - start
    print(f"[Gemini] 完成呼叫, 花費秒數: {elapsed:.2f}s")

    answer_text = getattr(response, "text", None)
    if not answer_text:
        return "抱歉，我暫時無法回答這個問題，請稍後再試一次～"

    return answer_text


def safe_reply_message(reply_token: str, text: str):
    """
    安全地呼叫 LINE 的 reply_message：
    - 如果網路問題導致連不到 api.line.me，就不讓錯誤往外丟，避免 /callback 變成 500。
    - 只在 server log 印出錯誤，方便你 debug。
    """
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=text),
        )
    except LineBotApiError as e:
        # LINE API 自身回傳錯誤（例如 token 無效、格式錯誤等）
        print("[LINE] LineBotApiError 發生：", e)
    except Exception as e:
        # 其他錯誤（requests 的 timeout、連線錯誤等）
        print("[LINE] 回覆訊息時發生非預期錯誤：", e)


@app.route("/callback", methods=["POST"])
def callback():
    """
    LINE 平台的 Webhook 入口：
    - LINE 會對這個 URL 發送 HTTP POST。
    - 這裡負責驗證簽章並把事件交給 handler 處理。
    """
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    print("[Callback] 收到請求 body:", body[:200], "...")  # 只印前 200 字

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[Callback] Invalid signature")
        abort(400)

    # 就算 handler 裡發生錯誤，只要沒往外丟，這裡都會回 200
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event: MessageEvent):
    """
    主事件處理函式：
    - 收到使用者文字訊息時會進到這裡。
    - 先處理設定個人資料的指令（身高 / 體重 / 目標）。
    - 其他文字則丟給 Gemini 做運動建議。
    """
    t0 = time.time()
    print("[LINE] 收到訊息事件")

    user_id = event.source.user_id
    text = event.message.text.strip()

    print(f"[LINE] user_id={user_id}, text={text}")

    # 第一次遇到這個 user_id 時，初始化一筆空的 profile
    if user_id not in user_profile:
        user_profile[user_id] = {}

    # ------------- 說明 / menu 指令 -------------
    if text in ["help", "Help", "說明", "menu"]:
        reply_text = (
            "嗨，我是你的運動 AI 小助手 💪\n\n"
            "你可以先設定你的基本資料：\n"
            "• 身高 170\n"
            "• 體重 65\n"
            "• 目標 減脂（或：增肌、比賽、健康維持等）\n\n"
            "之後再問我：\n"
            "• 想減脂一週可以運動三天，要怎麼安排？\n"
            "• 我想練馬拉松，有沒有訓練建議？\n"
            "• 上班久坐腰酸背痛，可以做什麼伸展？"
        )
        safe_reply_message(event.reply_token, reply_text)
        print(f"[LINE] 完成說明訊息, 花費秒數: {time.time() - t0:.2f}s")
        return

    # ------------- 設定身高 -------------
    if text.startswith("身高"):
        try:
            value_str = text.replace("身高", "").replace("cm", "").strip()
            height_value = int(value_str)
            user_profile[user_id]["height"] = height_value
            reply_text = f"已更新身高為 {height_value} cm！"
        except Exception:
            reply_text = "請用這種格式：身高 170（中間可以有空格）"

        safe_reply_message(event.reply_token, reply_text)
        print(f"[LINE] 更新身高完成, 花費秒數: {time.time() - t0:.2f}s")
        return

    # ------------- 設定體重 -------------
    if text.startswith("體重"):
        try:
            value_str = text.replace("體重", "").replace("kg", "").strip()
            weight_value = float(value_str)
            user_profile[user_id]["weight"] = weight_value
            reply_text = f"已更新體重為 {weight_value} kg！"
        except Exception:
            reply_text = "請用這種格式：體重 65 或 體重 65.5"

        safe_reply_message(event.reply_token, reply_text)
        print(f"[LINE] 更新體重完成, 花費秒數: {time.time() - t0:.2f}s")
        return

    # ------------- 設定目標 -------------
    if text.startswith("目標"):
        goal = text.replace("目標", "").strip()
        if not goal:
            reply_text = "請在『目標』後面加上你的目標，例如：目標 減脂 / 目標 增肌 / 目標 馬拉松。"
        else:
            user_profile[user_id]["goal"] = goal
            reply_text = f"已更新你的運動目標為：{goal}"

        safe_reply_message(event.reply_token, reply_text)
        print(f"[LINE] 更新目標完成, 花費秒數: {time.time() - t0:.2f}s")
        return

    # ------------- 一般問題：丟給 Gemini -------------
    try:
        reply_text = ask_gemini_sport_assistant(text, user_profile[user_id])
    except Exception as e:
        print("[LINE] 呼叫 Gemini 發生錯誤:", e)
        reply_text = "目前跟運動專家連線有點問題，請稍後再試試～"

    safe_reply_message(event.reply_token, reply_text)
    print(f"[LINE] 完成整體處理, 花費秒數: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    # 開發模式：在本機跑 Flask
    # 之後用：ngrok http 8000
    # Webhook URL 設成：https://xxxx.ngrok-free.app/callback
    app.run(host="0.0.0.0", port=8000, debug=True)
