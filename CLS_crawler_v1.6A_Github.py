# -*- coding: utf-8 -*-
"""
Created on Sun Jun 28 00:30:34 2026
重要教训：统一时间。
云端(GitHub Actions使用UTC+0标准时间)、本地编写(Python编译环境，即我的电脑，使用UTC+8北京时间)、爬虫网页(财联社根据访问者的系统时间决定)
@author: Fang Yizhou
"""

import time
import re
from datetime import datetime, timedelta, timezone
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from zai import ZhipuAiClient # 导入智谱 SDK, 需要安装 zai 和 zai-sdk

# ==================== 配置区域 ====================
URL = "https://www.cls.cn/telegraph"
CALENDAR_BTN_XPATH = '//div[contains(@class, "telegraph-querydate")]'   # //div[contains(@class, 'telegraph-querydate')][.//div[text()='日期']]
TODAY_BTN_XPATH = '//a[contains(@class, "rc-picker-now-btn")]'        # //div[contains(@class, 'telegraph-querydate-picker')]//a[text()='今天']
NEWS_LIST_XPATH = '//div[@class="c-b p-t-20 p-b-20 b-b-w-1 b-b-s-s b-c-e6e7ea"]'
NEWS_DATE_XPATH = './div[1]'
NEWS_CONTENT_XPATH = './/div[contains(@class, "search-content")]'
LOAD_MORE_XPATH = '//div[text()="加载更多"]'    # //div[contains(@class, "w-162") and contains(@class, "h-38") and contains(text(), "加载更多")]
# ==================================================

# 1. 无论在谁的电脑或云端，强行获取绝对的、统一的 UTC 零时区时间
utc_now = datetime.now(timezone.utc)
# 2. 在绝对零时区的基础上，统一往后拨 8 个小时，即标准的北京时间
now = utc_now.replace(tzinfo=None) + timedelta(hours=8)

time_limit = now - timedelta(hours=12.5)
print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"截止时间（12小时前）: {time_limit.strftime('%Y-%m-%d %H:%M:%S')}\n")

# 初始化浏览器
options = webdriver.ChromeOptions()
options.add_argument('--headless=new')  # 云端 Actions 必须开启无头模式
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
driver = webdriver.Chrome(options=options)
driver.execute_cdp_cmd(
    "Emulation.setTimezoneOverride",
    {"timezoneId": "Asia/Shanghai"}
)
driver.maximize_window()

all_data = []
stop_crawling = False

try:
    driver.get(URL)
    wait = WebDriverWait(driver, 15)

    # 1. 点击打开日历
    calendar_btn = wait.until(EC.element_to_be_clickable((By.XPATH, CALENDAR_BTN_XPATH)))
    calendar_btn.click()
    time.sleep(1)

    # 2. 点击“今天”
    today_btn = wait.until(EC.element_to_be_clickable((By.XPATH, TODAY_BTN_XPATH)))
    today_btn.click()
    time.sleep(2) # 等待切入整洁日历模式

    while not stop_crawling:
        # 3. 获取当前页面上所有的快讯卡片
        news_cards = driver.find_elements(By.XPATH, NEWS_LIST_XPATH)
        print(f"当前页面已加载 {len(news_cards)} 条快讯...")

        # 4. 检查最后一条新闻的时间，判断是否跨越了 12 小时
        if news_cards:
            try:
                # 定位到最后一张卡片中的时间节点
                last_time_node = news_cards[-1].find_element(By.XPATH, NEWS_DATE_XPATH)
                raw_time_text = last_time_node.text.strip()
                
                # 直接通过正则匹配出 YYYY-MM-DD HH:MM
                time_match = re.search(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}', raw_time_text)
                if time_match:
                    full_time_str = f"{time_match.group(0)}:00"
                    last_card_time = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M:%S")
                    
                    # 触发终止开关
                    if last_card_time < time_limit:
                        print(f"检测到末尾新闻时间为 {full_time_str}，已超出12小时范围。停止加载。")
                        stop_crawling = True
            except Exception as e:
                print("解析末尾时间失败，尝试继续加载...", e)

        if stop_crawling:
            break

        # 5. 点击“加载更多”
        try:
            # 采用更具弹性的包含匹配，避免因为多一个少一个空格导致精准定位失效
            load_more_btn = wait.until(EC.presence_of_element_located((By.XPATH, LOAD_MORE_XPATH)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_btn)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", load_more_btn)
            time.sleep(1.5) # 等待新内容加载
        except Exception as e:
            print("未找到【加载更多】按钮或已加载完毕:", e)
            break

    # 6. 精细化提取符合 12 小时内的数据
    print("\n开始精细化提取符合12小时内的数据...")
    final_cards = driver.find_elements(By.XPATH, NEWS_LIST_XPATH)
    
    for card in final_cards:
        try:
            # 6.1 提取时间
            time_node = card.find_element(By.XPATH, NEWS_DATE_XPATH)
            raw_time_text = time_node.text.strip()
            time_match = re.search(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}', raw_time_text)
            if not time_match:
                continue
                
            full_time_str = f"{time_match.group(0)}:00"
            card_time = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M:%S")
            
            # 严格过滤
            if card_time >= time_limit:
                # 6.2 提取正文
                content_node = card.find_element(By.XPATH, NEWS_CONTENT_XPATH)
                content_part = content_node.text.strip()
                
                # 6.3 分离【标题】与详细内容
                title_match = re.search(r'^【(.*?)】', content_part)
                if title_match:
                    title = title_match.group(1)
                    detail = content_part.replace(f"【{title}】", "").strip()
                else:
                    title = "" 
                    detail = content_part
                
                all_data.append({
                    "发布时间": full_time_str,
                    "新闻标题": title,
                    "详细内容": detail
                })
        except Exception:
            continue # 自动跳过非正常新闻结构（比如广告或者加载骨架屏）

finally:
    driver.quit()

# ==================== 自动化配置（从环境变量中读取，确保安全） ====================
# 这些变量我们会在 GitHub Settings 里配置，千万不要把密码明文写在代码里！

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") # 邮箱的授权码/客户端密码，不是登录密码
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
RECEIVER_EMAIL_2 = os.getenv("RECEIVER_EMAIL_2")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")    # 飞书 Webhook 链接

# ==============================================================================

if all_data:
    df = pd.DataFrame(all_data)
    df.drop_duplicates(subset=["发布时间", "详细内容"], inplace=True)
    
    filename = f"财联社电报_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(filename, index=False, engine='openpyxl')
    print(f"\n 成功抓取到 {len(df)} 条快讯！已保存至：{filename}")
    
    # ---- 1. 分批调用 GLM-4.7 Flash 模型进行总结 ----
    print("\n正在调用 GLM-4.7 Flash 提炼财经日报...")
    
    # 设定每批处理的新闻条数（输入token长度限制200k，每次最大处理量约600条，按每条新闻300token计）
    CHUNK_SIZE = 210
    all_summary_pieces = [] # 存放每一批 AI 总结出来的结果
    # 定义首选模型和备用模型
    PRIMARY_MODEL = "glm-4.7-flash"
    BACKUP_MODEL = "glm-4.6v-flash" # 作为备胎

    # 利用 Python 的 range 步长进行切片循环
    for i in range(0, len(df), CHUNK_SIZE):
        chunk_df = df.iloc[i : i + CHUNK_SIZE]
        print(f"正在处理第 {i+1} 到 {i + len(chunk_df)} 条快讯... (当前进度: {i+1}/{len(df)})")
        
        # 将当前批次的数据拼接成文本
        raw_news_text = ""
        for idx, row in chunk_df.iterrows():
            title_part = f"【{row['新闻标题']}】" if row['新闻标题'] else ""
            raw_news_text += f"时间: {row['发布时间']} | {title_part}{row['详细内容']}\n"
        
        # --- 核心抗噪重试逻辑 ---
        current_model = PRIMARY_MODEL
        MAX_RETRIES = 2 # 每批数据最多重试 ? 次
        chunk_success = False
        
        for retry in range(MAX_RETRIES):
            try:
                # 实例化新版 zai 客户端
                client = ZhipuAiClient(api_key=ZHIPU_API_KEY)
                
                api_kwargs = {
                    "model": current_model,
                    "messages": [
                        {
                            "role": "system", 
                            "content": (
                                "你是资深证券分析师。请对用户提供的财联社电报内容进行筛选和提炼。\n\n"
                                "【硬性限制】\n"
                                "1. 本批次数据中，每条独立的重大资讯必须作为单独的一个 Bullet Point（列表要点）列出，严禁多条合并。\n"
                                "2. 本批次数据中，总输出条数不超过 15 条。\n"
                                "3. 每条字数严禁超过 180 字。在基本保留原文核心事实（公司/代码/金额/核心逻辑等等）的前提下进行语义去冗余和逻辑精简。\n\n"
                                "【筛选原则】\n"
                                "严格剔除：民生琐事、常规的盘中价格波动和播报、一般的公司常规公告、无剧烈影响的国际新闻。\n\n"
                                "核心保留：\n"
                                "- 【宏观经济与政策】：涉及央行、监管层、重大宏观数据、重大地缘政治变动... \n"
                                "- 【行业核心异动与风向标】：板块投资逻辑变化、产业核心技术突破... \n"
                                "- 【重要上市公司公告】：业绩预增/暴跌、核心股东巨额减持... \n"
                                "【输出样式】\n"
                                "请按上述三大保留板块作为标题输出，若某板块无重大资讯则该板块留空。"
                            )
                        },
                        {"role": "user", "content": raw_news_text}
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": 33000,
                        "temperature": 0.2
                    }
                
                response = client.chat.completions.create(**api_kwargs)
                
                # 把这一批的成果塞进大列表
                chunk_result = response.choices[0].message.content
                all_summary_pieces.append(chunk_result)
                chunk_success = True
                print(f"✅ 第 {i+1} 批使用模型 [{current_model}] 总结成功！最终使用模型: [{current_model}]")
                # 【重要：防抖冷却】每处理完一批，让程序强制“睡” 2 秒，彻底洗掉智谱平台的 RPM 并发限流
                time.sleep(5)
                break   # 若成功，立刻跳出当前的重试循环，去处理下一批新闻
                
            except Exception as e:
                error_msg = str(e)
                
                # 如果遇到 1305 访问量过大，启动策略：切换备用模型 + 延迟重试
                is_congestion = "1305" in error_msg or "访问量过大" in error_msg
                # 如果还没到最后一次重试，我们死守主模型，只是原地睡觉等待服务器恢复
                if retry < MAX_RETRIES - 1:
                    wait_time = (retry + 1) * 10 # 递增等待时间：5秒、10秒
                    if is_congestion:
                        print(f"   ⚠️ 触发全网拥堵(1305)。主模型坚守中，将在 {wait_time} 秒后进行下一次重试...")
                    else:
                        print(f"   ⚠️ 接口调用抖动。将在 {wait_time} 秒后进行下一次重试...")
                    time.sleep(wait_time)
                else:
                    if is_congestion:
                        print(f"   🚨 连续 {MAX_RETRIES} 次触发 1305 拥堵。降级为备用模型 [{BACKUP_MODEL}]！")
                        current_model = BACKUP_MODEL
                        try:
                            api_kwargs["model"] = BACKUP_MODEL
                            response = client.chat.completions.create(**api_kwargs)
                            chunk_result = response.choices[0].message.content
                            all_summary_pieces.append(chunk_result)
                            chunk_success = True
                            print(f"   🎉 成功使用备用模型 [{BACKUP_MODEL}] 挽回本批次数据！")
                            time.sleep(5)
                        except Exception as backup_err:
                            print(f"   ❌ 严重警告：备用模型失败，原因为: {backup_err}")
                    else:
                        # 别的顽固错误（非1305），直接报错结束
                        print(f"   ❌ 第 {i+1} 批数据在重试 {MAX_RETRIES} 次后因非拥堵原因彻底失败。")
        if not chunk_success:
            print(f"🚨 警告：第 {i+1} 批数据已彻底丢失，跳过此批。")

    # ---- 2. 最终合并汇总结果 ----
    # 用两个换行符把所有批次的总结串联起来，这就成了你最终的完整日报正文
    ai_summary = "\n\n=========================================\n\n".join(all_summary_pieces)
    print("💡 全量分批 AI 总结生成并合并成功！")
    # print(ai_summary) # Used for local checks

    # ---- 3. 自动化推送 ----
    print("\n开始通过邮件向主人推送日报...")
    try:
        # 构建复杂的邮件结构（支持正文+附件）
        # 核心步骤 1：把两个收件人地址打包成一个 Python 列表（List）
        to_addrs = [RECEIVER_EMAIL, RECEIVER_EMAIL_2]
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        # 核心步骤 2：msg['To'] 接收的是一个“用英文逗号分隔的字符串”，而不是列表！
        msg['To'] = ", ".join(to_addrs)
        # msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"🤖 AI 财经简报 - {now.strftime('%Y-%m-%d %H:%M')}"
        # 将 AI 总结放入邮件正文（支持 Markdown 或纯文本）
        msg.attach(MIMEText(ai_summary, 'plain', 'utf-8'))
        
        # 挂载原始的 Excel 附件
        with open(filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            # 核心修正 1：使用 Header 对包含中文的文件名进行标准邮件编码转换, filename 会被包装成像 =?utf-8?b?xxxx?= 的标准格式
            encoded_filename = Header(filename, 'utf-8').encode()
            # 核心修正 2：在 Content-Disposition 中传入编码后的文件名
            part.add_header("Content-Disposition", "attachment", filename=encoded_filename)
            msg.attach(part)
            
        # 连接 SMTP 服务器发送
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        # 核心步骤 3：
        server.sendmail(SENDER_EMAIL, to_addrs, msg.as_string())
        server.quit()
        print("📬 邮件及 Excel 附件已成功送达邮箱！")
    except Exception as e:
        print(f"邮件发送失败: {e}")
        
    # ---- 3. 【新增】飞书 Webhook 机器人推送 ----
    print("\n开始通过飞书机器人推送日报...")
    try:
        # 构造飞书标准的富文本（post）消息格式
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📈 AI 财经早/晚报 ({now.strftime('%Y-%m-%d %H:%M')})",
                        "content": [
                            # 飞书支持按行渲染。为了保证体验，我们将 AI 总结按行切分喂给飞书
                            [{"tag": "text", "text": line}] for line in ai_summary.split("\n")
                        ]
                    }
                }
            }
        }
        
        # 发送 POST 请求
        response = requests.post(FEISHU_WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"})
        response_json = response.json()
        
        # 飞书成功返回码为 0
        if response_json.get("code") == 0:
            print("🕊️ 飞书机器人日报卡片推送成功！")
        else:
            print(f"❌ 飞书推送失败，飞书服务器返回: {response_json.get('msg')}")
    except Exception as fe:
        print(f"飞书组件运行异常: {fe}")

else:
    print("\n 没有抓取到任何符合条件的数据。")
