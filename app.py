import os
import psycopg2
from flask import Flask, request, render_template_string, redirect, url_for, session
import datetime

app = Flask(__name__)
app.secret_key = 'luban_repair_secret_key'

ADMIN_PASSWORD = "luban888"

# 魯班手機維修店面座標與 50 公尺限制
STORE_LAT = 22.686950
STORE_LNG = 120.309500
MAX_DISTANCE_METERS = 50  # 限制 50 公尺內

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("未設定 DATABASE_URL 環境變數，請確認 Render 後台設定。")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(db_url)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS records
                 (id SERIAL PRIMARY KEY,
                  emp_name VARCHAR(100),
                  action VARCHAR(50),
                  leave_code VARCHAR(50),
                  timestamp TIMESTAMP,
                  ip_address VARCHAR(50))''')
    c.execute('''CREATE TABLE IF NOT EXISTS employees
                 (id SERIAL PRIMARY KEY,
                  name VARCHAR(100))''')
    conn.commit()
    c.close()
    conn.close()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>魯班手機維修 - 員工出勤系統</title>
    <style>
        body { font-family: '微軟正黑體', sans-serif; text-align: center; padding: 20px; background-color: #f0f2f5; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 400px; margin: 20px auto; }
        h2 { color: #333; margin-bottom: 20px; }
        select, button { width: 100%; box-sizing: border-box; padding: 12px; margin: 10px 0; border-radius: 8px; border: 1px solid #ccc; font-size: 16px; }
        button { background-color: #007bff; color: white; border: none; cursor: pointer; font-weight: bold; font-size: 18px; margin-top: 20px; transition: 0.3s; }
        button:hover { background-color: #0056b3; }
        .message { margin-top: 20px; font-weight: bold; font-size: 1.1em; color: #d9534f; }
        .success { color: #28a745; }
        .footer { margin-top: 30px; font-size: 0.8em; color: #888; }
        .admin-link { margin-top: 20px; display: block; color: #666; text-decoration: none; font-size: 0.9em; }
        .admin-link:hover { color: #007bff; }
    </style>
    <script>
        function verifyLocation(event) {
            event.preventDefault(); // 暫停預設提交
            
            if (!navigator.geolocation) {
                alert("您的瀏覽器不支援定位功能，無法打卡！");
                return;
            }

            const btn = document.getElementById('submit-btn');
            btn.innerText = "正在進行店面 GPS 定位驗證...";
            btn.disabled = true;

            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const userLat = position.coords.latitude;
                    const userLng = position.coords.longitude;
                    
                    // 計算與店面的距離 (公尺)
                    const storeLat = {{ store_lat }};
                    const storeLng = {{ store_lng }};
                    const maxDist = {{ max_dist }};

                    const distance = getDistanceFromLatLonInMeters(userLat, userLng, storeLat, storeLng);

                    if (distance > maxDist) {
                        alert("❌ 距離店面太遠 (" + Math.round(distance) + "公尺)。必須在店面 50 公尺範圍內才能打卡！");
                        btn.innerText = "送出打卡紀錄";
                        btn.disabled = false;
                    } else {
                        // 通過距離驗證，把經緯度塞入表單送出
                        const form = document.getElementById('clock-form');
                        
                        let inputLat = document.createElement('input');
                        inputLat.type = 'hidden';
                        inputLat.name = 'lat';
                        inputLat.value = userLat;
                        form.appendChild(inputLat);

                        let inputLng = document.createElement('input');
                        inputLng.type = 'hidden';
                        inputLng.name = 'lng';
                        inputLng.value = userLng;
                        form.appendChild(inputLng);

                        form.submit();
                    }
                },
                function(error) {
                    alert("❌ 無法取得您的 GPS 定位，請確認手機已開啟定位權限並再試一次！");
                    btn.innerText = "送出打卡紀錄";
                    btn.disabled = false;
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        }

        function getDistanceFromLatLonInMeters(lat1, lon1, lat2, lon2) {
            const R = 6371000; // Radius of earth in meters
            const dLat = deg2rad(lat2-lat1);
            const dLon = deg2rad(lon2-lon1); 
            const a = 
                Math.sin(dLat/2) * Math.sin(dLat/2) +
                Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) * 
                Math.sin(dLon/2) * Math.sin(dLon/2)
            ; 
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)); 
            return R * c;
        }

        function deg2rad(deg) {
            return deg * (Math.PI/180);
        }
    </script>
</head>
<body>
    <div class="container">
        <h2>🛠️ 魯班手機維修<br>員工出勤系統</h2>
        
        <form id="clock-form" method="POST" action="/" onsubmit="verifyLocation(event)">
            <select name="emp_name" required>
                <option value="" disabled selected>-- 請選擇您的名字 --</option>
                {% for emp in employees %}
                    <option value="{{ emp }}">{{ emp }}</option>
                {% endfor %}
            </select>
            
            <select name="action" required>
                <option value="上班">上班 (Clock In)</option>
                <option value="下班">下班 (Clock Out)</option>
                <option value="請假">請假 (Leave)</option>
            </select>
            
            <select name="leave_code">
                <option value="">請假代號 (非請假免填)</option>
                <option value="特">特 (特休 - 不計入工時)</option>
                <option value="病">病 (病假)</option>
                <option value="事">事 (事假)</option>
                <option value="其他">其他</option>
            </select>
            
            <button type="submit" id="submit-btn">送出打卡紀錄</button>
        </form>

        {% if message %}
            <div class="message {% if success %}success{% endif %}">{{ message }}</div>
        {% endif %}
        
        <a href="/admin" class="admin-link">⚙️ 老闆後台管理</a>
    </div>
    <div class="footer">Luban Mobile Repair System (GPS 50m Lock)</div>
</body>
</html>
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>魯班手機維修 - 老闆管理後台</title>
    <style>
        body { font-family: '微軟正黑體', sans-serif; padding: 20px; background-color: #f8f9fa; }
        .container { max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h2, h3 { color: #333; }
        input, button { padding: 10px; margin: 5px 0; border-radius: 5px; border: 1px solid #ccc; font-size: 15px; }
        button { background-color: #28a745; color: white; border: none; cursor: pointer; font-weight: bold; }
        button.danger { background-color: #dc3545; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #dee2e6; padding: 12px; text-align: center; }
        th { background-color: #007bff; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .section { margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #eee; }
        .back-link { display: inline-block; margin-bottom: 15px; color: #007bff; text-decoration: none; }
        ul { list-style-type: none; padding: 0; }
        li { background: #f1f3f5; margin: 6px 0; padding: 8px 14px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .alert-success { background-color: #d4edda; color: #155724; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
        .alert-danger { background-color: #f8d7da; color: #721c24; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
        .status-tag { display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 0.9em; font-weight: bold; margin-bottom: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">← 返回打卡首頁</a>
        <h2>⚙️ 魯班手機維修 - 管理員後台</h2>

        {% if not logged_in %}
            <form method="POST" action="/admin">
                <h3>請輸入管理者密碼</h3>
                <input type="password" name="password" placeholder="請輸入密碼" required>
                <button type="submit">登入</button>
                {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
            </form>
        {% else %}
            <div class="status-tag" style="background-color: #e9ecef;">{{ db_status }}</div>

            {% if msg %}
                <div class="alert-success">{{ msg }}</div>
            {% endif %}
            {% if error %}
                <div class="alert-danger">{{ error }}</div>
            {% endif %}

            <div class="section">
                <h3>👥 員工名單管理 (新增/刪除)</h3>
                <form method="POST" action="/admin/employee">
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <input type="text" name="new_emp_name" placeholder="輸入新員工姓名" required style="flex: 1; margin: 0;">
                        <button type="submit" style="margin: 0; width: auto; padding: 10px 24px;">新增員工</button>
                    </div>
                </form>

                <ul style="margin-top: 15px;">
                    {% if employees %}
                        {% for emp in employees %}
                            <li>
                                <strong style="font-size: 16px;">{{ emp }}</strong>
                                <form action="/admin/employee/delete" method="POST" style="margin:0;">
                                    <input type="hidden" name="emp_name" value="{{ emp }}">
                                    <button type="submit" class="danger" style="padding:4px 12px; font-size:13px; margin:0; width:auto;">刪除</button>
                                </form>
                            </li>
                        {% endfor %}
                    {% else %}
                        <li style="background: transparent; color: #888; justify-content: center;">目前名單中尚無員工，請在上方輸入姓名新增。</li>
                    {% endif %}
                </ul>
            </div>

            <div class="section">
                <h3>📋 員工出勤與請假紀錄總覽</h3>
                <table>
                    <tr>
                        <th>編號</th>
                        <th>員工姓名</th>
                        <th>狀態</th>
                        <th>請假代號</th>
                        <th>打卡時間</th>
                        <th>IP 位址</th>
                    </tr>
                    {% for row in records %}
                    <tr>
                        <td>{{ row[0] }}</td>
                        <td>{{ row[1] }}</td>
                        <td>{{ row[2] }}</td>
                        <td>{{ row[3] if row[3] else '-' }}</td>
                        <td>{{ row[4] }}</td>
                        <td>{{ row[5] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
            <a href="/admin/logout"><button class="danger" style="width: auto; padding: 10px 20px;">登出後台</button></a>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    success = False
    employees = []

    try:
        init_db()
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT name FROM employees ORDER BY id")
        employees = [row[0] for row in c.fetchall()]
        c.close()
        conn.close()
    except Exception as e:
        message = f"讀取名單失敗: {e}"

    if request.method == 'POST':
        emp_name = request.form.get('emp_name')
        action = request.form.get('action')
        leave_code = request.form.get('leave_code', '').strip()
        
        if request.headers.getlist("X-Forwarded-For"):
            user_ip = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
        else:
            user_ip = request.remote_addr
        
        try:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO records (emp_name, action, leave_code, timestamp, ip_address) VALUES (%s, %s, %s, %s, %s)",
                      (emp_name, action, leave_code, current_time, user_ip))
            conn.commit()
            c.close()
            conn.close()
            
            success = True
            if action == "請假" and leave_code == "特":
                message = f"✅ {emp_name} 特休登記成功！(已排除工時計算)"
            else:
                message = f"✅ {emp_name} {action} 紀錄已同步！"
        except Exception as e:
            message = f"❌ 系統錯誤：{e}"

    return render_template_string(HTML_TEMPLATE, employees=employees, message=message, success=success, store_lat=STORE_LAT, store_lng=STORE_LNG, max_dist=MAX_DISTANCE_METERS)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    logged_in = session.get('logged_in', False)
    error = session.pop('admin_err', '')
    msg = session.pop('admin_msg', '')
    
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            logged_in = True
        else:
            error = "密碼錯誤，請重新輸入！"

    employees = []
    records = []
    db_status = "連線檢查中..."

    if logged_in:
        try:
            init_db()
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT name FROM employees ORDER BY id")
            employees = [row[0] for row in c.fetchall()]
            c.execute("SELECT id, emp_name, action, leave_code, timestamp, ip_address FROM records ORDER BY id DESC")
            records = c.fetchall()
            c.close()
            conn.close()
            db_status = "🟢 資料庫連線正常 (GPS 50公尺防護中)"
        except Exception as e:
            db_status = f"🔴 資料庫連線異常: {e}"

    return render_template_string(ADMIN_TEMPLATE, logged_in=logged_in, error=error, msg=msg, db_status=db_status, employees=employees, records=records)

@app.route('/admin/employee', methods=['POST'])
def add_employee():
    if not session.get('logged_in'):
        return redirect(url_for('admin'))
    
    new_emp = request.form.get('new_emp_name', '').strip()
    if new_emp:
        try:
            init_db()
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM employees WHERE name = %s", (new_emp,))
            if not c.fetchone():
                c.execute("INSERT INTO employees (name) VALUES (%s)", (new_emp,))
                conn.commit()
                session['admin_msg'] = f"✅ 成功新增員工：{new_emp}"
            else:
                session['admin_err'] = f"⚠️ 員工「{new_emp}」已在名單中！"
            c.close()
            conn.close()
        except Exception as e:
            session['admin_err'] = f"❌ 新增失敗，資料庫錯誤：{e}"
            
    return redirect(url_for('admin'))

@app.route('/admin/employee/delete', methods=['POST'])
def delete_employee():
    if not session.get('logged_in'):
        return redirect(url_for('admin'))
    
    emp_name = request.form.get('emp_name')
    if emp_name:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM employees WHERE name = %s", (emp_name,))
            conn.commit()
            c.close()
            conn.close()
            session['admin_msg'] = f"✅ 已成功刪除員工：{emp_name}"
        except Exception as e:
            session['admin_err'] = f"❌ 刪除失敗：{e}"
            
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run()
