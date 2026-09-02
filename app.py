import os
import psycopg2
from flask import Flask, request, render_template_string
import datetime

app = Flask(__name__)

# 店內 Wi-Fi 路由器的對外 IP (之後請換成魯班手機維修店裡的真實 IP)
STORE_PUBLIC_IP = "123.45.67.89" 

def get_db_connection():
    # 抓取 Render 環境變數中的資料庫網址
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("沒有找到 DATABASE_URL 環境變數，請在 Render 後台設定。")
    conn = psycopg2.connect(db_url)
    return conn

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS records
                     (id SERIAL PRIMARY KEY,
                      emp_name VARCHAR(100),
                      action VARCHAR(50),
                      leave_code VARCHAR(50),
                      timestamp TIMESTAMP,
                      ip_address VARCHAR(50))''')
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        print(f"資料庫初始化提示: 稍後在 Render 設定好 DATABASE_URL 後即會正常連線。({e})")

# 啟動時自動建立資料表
init_db()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>魯班手機維修 - 員工打卡</title>
    <style>
        body { font-family: '微軟正黑體', sans-serif; text-align: center; padding: 20px; background-color: #f0f2f5; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 400px; margin: 20px auto; }
        h2 { color: #333; margin-bottom: 20px; }
        input, select, button { width: 100%; box-sizing: border-box; padding: 12px; margin: 10px 0; border-radius: 8px; border: 1px solid #ccc; font-size: 16px; }
        button { background-color: #007bff; color: white; border: none; cursor: pointer; font-weight: bold; font-size: 18px; margin-top: 20px; transition: 0.3s; }
        button:hover { background-color: #0056b3; }
        .message { margin-top: 20px; font-weight: bold; font-size: 1.1em; color: #d9534f; }
        .success { color: #28a745; }
        .footer { margin-top: 30px; font-size: 0.8em; color: #888; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🛠️ 魯班手機維修<br>員工出勤系統</h2>
        
        <form method="POST" action="/">
            <input type="text" name="emp_name" placeholder="請輸入員工姓名" required>
            
            <select name="action" required>
                <option value="上班">上班 (Clock In)</option>
                <option value="下班">下班 (Clock Out)</option>
                <option value="請假">請假 (Leave)</option>
            </select>
            
            <input type="text" name="leave_code" placeholder="請假代號 (如: 特、病) - 僅請假需填">
            
            <button type="submit">送出紀錄</button>
        </form>

        {% if message %}
            <div class="message {% if success %}success{% endif %}">{{ message }}</div>
        {% endif %}
    </div>
    <div class="footer">Luban Mobile Repair System</div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    success = False

    if request.method == 'POST':
        emp_name = request.form.get('emp_name')
        action = request.form.get('action')
        leave_code = request.form.get('leave_code', '').strip()
        
        # 抓取真實 IP (Render 環境下需讀取 X-Forwarded-For)
        if request.headers.getlist("X-Forwarded-For"):
            user_ip = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
        else:
            user_ip = request.remote_addr

        # ---------------------------------------------------------
        # 【Wi-Fi 驗證區】
        # 目前先幫您暫時註解掉，讓您剛架設好時可以用自己的手機 4G 測試。
        # 測試成功後，把下面這兩行前面的 # 拿掉，就會開啟 Wi-Fi 限制了！
        # ---------------------------------------------------------
        # if action in ["上班", "下班"] and user_ip != STORE_PUBLIC_IP:
        #     message = f"❌ 打卡失敗：請確認已連接店內 Wi-Fi (偵測到 IP: {user_ip})"
        # else:
        
        try:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            c = conn.cursor()
            
            # 寫入資料庫
            c.execute("INSERT INTO records (emp_name, action, leave_code, timestamp, ip_address) VALUES (%s, %s, %s, %s, %s)",
                      (emp_name, action, leave_code, current_time, user_ip))
            conn.commit()
            c.close()
            conn.close()
            
            success = True
            
            # 若為請假且代號為特休，給予特殊提示 (方便後續結算天數排除)
            if action == "請假" and leave_code == "特":
                message = f"✅ {emp_name} 特休登記成功！(不計入當月排班工時)"
            else:
                message = f"✅ {emp_name} {action} 紀錄已同步至雲端！"
                
        except Exception as e:
            message = f"❌ 系統錯誤，請聯絡管理員：{e}"

    return render_template_string(HTML_TEMPLATE, message=message, success=success)

if __name__ == '__main__':
    # Render 環境預設會給 PORT 環境變數
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
