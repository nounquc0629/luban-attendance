import os
import psycopg2
from flask import Flask, request, render_template_string, redirect, url_for, session
import datetime

app = Flask(__name__)
app.secret_key = 'luban_repair_secret_key'

ADMIN_PASSWORD = "luban888"

# 魯班手機維修店面座標與 30 公尺限制
STORE_LAT = 22.686950
STORE_LNG = 120.309500
MAX_DISTANCE_METERS = 30

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
                  name VARCHAR(100),
                  hire_date DATE)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS schedules
                 (id SERIAL PRIMARY KEY,
                  emp_name VARCHAR(100),
                  off_date DATE)''')
    
    c.execute('''ALTER TABLE employees ADD COLUMN IF NOT EXISTS hire_date DATE''')
    
    conn.commit()
    c.close()
    conn.close()

# 勞基法特休計算邏輯
def calculate_annual_leave(hire_date):
    if not hire_date:
        return 0
    today = datetime.date.today()
    service_days = (today - hire_date).days
    if service_days < 180:
        return 0
    
    service_years = service_days / 365.25
    
    if service_years < 1:
        return 3
    elif service_years < 2:
        return 7
    elif service_years < 3:
        return 10
    elif service_years < 5:
        return 14
    elif service_years < 10:
        return 15
    else:
        days = 15 + int(service_years - 10)
        return min(days, 30)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>魯班手機維修 - 員工出勤系統</title>
    <style>
        body { font-family: '微軟正黑體', sans-serif; text-align: center; padding: 20px; background-color: #f0f2f5; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 420px; margin: 20px auto; }
        h2 { color: #333; margin-bottom: 20px; }
        select, button { width: 100%; box-sizing: border-box; padding: 12px; margin: 10px 0; border-radius: 8px; border: 1px solid #ccc; font-size: 16px; }
        .btn-group { display: flex; gap: 12px; margin: 15px 0 10px; }
        .btn-work { background-color: #28a745; color: white; border: none; font-size: 18px; font-weight: bold; cursor: pointer; border-radius: 8px; padding: 14px 0; flex: 1; transition: 0.2s; }
        .btn-work:hover { background-color: #218838; }
        .btn-off { background-color: #dc3545; color: white; border: none; font-size: 18px; font-weight: bold; cursor: pointer; border-radius: 8px; padding: 14px 0; flex: 1; transition: 0.2s; }
        .btn-off:hover { background-color: #c82333; }
        .leave-box { border-top: 1px dashed #ccc; margin-top: 20px; padding-top: 15px; }
        .btn-leave { background-color: #6c757d; color: white; border: none; font-size: 16px; cursor: pointer; border-radius: 8px; padding: 10px 0; }
        .btn-leave:hover { background-color: #5a6268; }
        .message { margin-top: 20px; font-weight: bold; font-size: 1.1em; color: #d9534f; }
        .success { color: #28a745; }
        .footer { margin-top: 30px; font-size: 0.8em; color: #888; }
        .admin-link { margin-top: 20px; display: block; color: #666; text-decoration: none; font-size: 0.9em; }
        .admin-link:hover { color: #007bff; }
    </style>
    <script>
        let currentAction = '';

        function submitClock(actionName) {
            const empSelect = document.getElementById('emp-select');
            if (!empSelect.value) {
                alert("⚠️ 請先選擇您的名字！");
                empSelect.focus();
                return;
            }

            let confirmMsg = "";
            if (actionName === '請假') {
                const leaveSelect = document.getElementById('leave-select');
                const leaveText = leaveSelect.options[leaveSelect.selectedIndex].text;
                if (!leaveSelect.value) {
                    alert("⚠️ 請先選擇請假代號！");
                    return;
                }
                confirmMsg = "❓【打卡確認】\\n員工：" + empSelect.value + "\\n類別：請假 (" + leaveText + ")\\n\\n確定要送出請假申請嗎？";
            } else {
                confirmMsg = "❓【打卡確認】\\n員工：" + empSelect.value + "\\n動作：" + actionName + "\\n\\n確定要送出【" + actionName + "】打卡嗎？請確認未按錯！";
            }

            // 二次防呆提醒
            if (!confirm(confirmMsg)) {
                return; // 員工點取消，中斷送出
            }

            currentAction = actionName;
            document.getElementById('action-input').value = actionName;

            if (!navigator.geolocation) {
                alert("您的瀏覽器不支援定位功能，無法打卡！");
                return;
            }

            setButtonsDisabled(true, "正在進行 GPS 定位驗證...");

            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const userLat = position.coords.latitude;
                    const userLng = position.coords.longitude;
                    const storeLat = {{ store_lat }};
                    const storeLng = {{ store_lng }};
                    const maxDist = {{ max_dist }};

                    const distance = getDistanceFromLatLonInMeters(userLat, userLng, storeLat, storeLng);

                    if (distance > maxDist) {
                        alert("❌ 距離店面太遠 (" + Math.round(distance) + "公尺)。必須在店面 " + maxDist + " 公尺範圍內才能打卡！");
                        setButtonsDisabled(false);
                    } else {
                        const form = document.getElementById('clock-form');
                        document.getElementById('input-lat').value = userLat;
                        document.getElementById('input-lng').value = userLng;
                        form.submit();
                    }
                },
                function(error) {
                    alert("❌ 無法取得您的 GPS 定位，請確認手機已開啟定位權限並再試一次！");
                    setButtonsDisabled(false);
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
            );
        }

        function setButtonsDisabled(state, text) {
            const btnWork = document.getElementById('btn-work');
            const btnOff = document.getElementById('btn-off');
            const btnLeave = document.getElementById('btn-leave');
            btnWork.disabled = state;
            btnOff.disabled = state;
            if (btnLeave) btnLeave.disabled = state;

            if (state && text) {
                if (currentAction === '上班') btnWork.innerText = text;
                else if (currentAction === '下班') btnOff.innerText = text;
                else if (btnLeave) btnLeave.innerText = text;
            } else {
                btnWork.innerText = "🟢 上班 (Clock In)";
                btnOff.innerText = "🔴 下班 (Clock Out)";
                if (btnLeave) btnLeave.innerText = "送出請假申請";
            }
        }

        function getDistanceFromLatLonInMeters(lat1, lon1, lat2, lon2) {
            const R = 6371000;
            const dLat = deg2rad(lat2-lat1);
            const dLon = deg2rad(lon2-lon1); 
            const a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) * Math.sin(dLon/2) * Math.sin(dLon/2); 
            return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)));
        }
        function deg2rad(deg) { return deg * (Math.PI/180); }
    </script>
</head>
<body>
    <div class="container">
        <h2>🛠️ 魯班手機維修<br>員工出勤系統</h2>
        <form id="clock-form" method="POST" action="/">
            <input type="hidden" name="action" id="action-input" value="">
            <input type="hidden" name="lat" id="input-lat" value="">
            <input type="hidden" name="lng" id="input-lng" value="">

            <select name="emp_name" id="emp-select" required>
                <option value="" disabled selected>-- 請選擇您的名字 --</option>
                {% for emp in employees %}
                    <option value="{{ emp[0] }}">{{ emp[0] }}</option>
                {% endfor %}
            </select>

            <!-- 直覺的大按鍵 -->
            <div class="btn-group">
                <button type="button" id="btn-work" class="btn-work" onclick="submitClock('上班')">🟢 上班 (Clock In)</button>
                <button type="button" id="btn-off" class="btn-off" onclick="submitClock('下班')">🔴 下班 (Clock Out)</button>
            </div>

            <div class="leave-box">
                <select name="leave_code" id="leave-select">
                    <option value="">請選擇請假代號 (非請假免選)</option>
                    <option value="特">特休假 (有薪)</option>
                    <option value="病">普通傷病假 (半薪)</option>
                    <option value="事">事假 (無薪)</option>
                    <option value="婚">婚假 (有薪)</option>
                    <option value="喪">喪假 (有薪)</option>
                    <option value="陪">陪產假 (有薪)</option>
                    <option value="產">產假/產檢假 (有薪)</option>
                    <option value="其他">其他</option>
                </select>
                <button type="button" id="btn-leave" class="btn-leave" onclick="submitClock('請假')">送出請假申請</button>
            </div>
        </form>

        {% if message %}
            <div class="message {% if success %}success{% endif %}">{{ message }}</div>
        {% endif %}
        <a href="/admin" class="admin-link">⚙️ 老闆後台管理</a>
    </div>
    <div class="footer">Luban Mobile Repair System (GPS {{ max_dist }}m Lock)</div>
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
        .container { max-width: 1200px; margin: auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h2, h3 { color: #333; }
        input, button, select { padding: 10px; margin: 5px 0; border-radius: 5px; border: 1px solid #ccc; font-size: 15px; }
        button { background-color: #28a745; color: white; border: none; cursor: pointer; font-weight: bold; }
        button.danger { background-color: #dc3545; }
        button.edit-btn { background-color: #ffc107; color: #212529; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #dee2e6; padding: 10px; text-align: center; font-size: 13px; }
        th { background-color: #007bff; color: white; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .section { margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #eee; }
        .back-link { display: inline-block; margin-bottom: 15px; color: #007bff; text-decoration: none; }
        ul { list-style-type: none; padding: 0; }
        li { background: #f1f3f5; margin: 6px 0; padding: 10px 14px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .alert-success { background-color: #d4edda; color: #155724; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
        .alert-danger { background-color: #f8d7da; color: #721c24; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
        .status-tag { display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 0.9em; font-weight: bold; margin-bottom: 15px; background-color: #e9ecef; }
        .month-selector { background: #e8f4fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; gap: 15px; }

        /* 修改打卡彈跳視窗 Modal */
        .modal { display: none; position: fixed; z-index: 999; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); }
        .modal-content { background-color: #fff; margin: 10% auto; padding: 25px; border-radius: 8px; width: 90%; max-width: 450px; text-align: left; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
        .modal-header { font-size: 18px; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid #ddd; padding-bottom: 10px; }
        .modal-body label { font-size: 14px; font-weight: bold; display: block; margin-top: 10px; }
        .modal-body input, .modal-body select { width: 100%; box-sizing: border-box; }
        .modal-footer { margin-top: 20px; text-align: right; }
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
            <div class="status-tag">{{ db_status }}</div>

            {% if msg %}<div class="alert-success">{{ msg }}</div>{% endif %}
            {% if error %}<div class="alert-danger">{{ error }}</div>{% endif %}

            <!-- 全局月份選擇器 -->
            <div class="month-selector">
                <form method="GET" action="/admin" style="display: flex; gap: 10px; align-items: center; margin: 0; flex-wrap: wrap;">
                    <label for="month" style="font-weight: bold; font-size: 16px; color: #0056b3;">📅 選擇查看月份：</label>
                    <input type="month" id="month" name="month" value="{{ selected_month }}" style="margin: 0; font-size: 16px;">
                    <button type="submit" style="background-color: #007bff; margin: 0; width: auto; padding: 10px 18px;">切換月份資料</button>
                </form>
                <span style="font-size: 13px; color: #666;">（目前僅顯示 <b>{{ selected_month }}</b> 月份的結算報表、排休與打卡紀錄）</span>
            </div>

            <!-- 員工名單與特休 -->
            <div class="section">
                <h3>👥 員工名單與法定特休額度</h3>
                <form method="POST" action="/admin/employee">
                    <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                        <input type="text" name="new_emp_name" placeholder="輸入新員工姓名" required style="flex: 1; margin: 0; min-width: 150px;">
                        <span style="font-size: 14px; color: #555;">到職日:</span>
                        <input type="date" name="hire_date" value="{{ today_str }}" required style="margin: 0;">
                        <button type="submit" style="margin: 0; width: auto; padding: 10px 20px;">新增員工</button>
                    </div>
                </form>

                <ul style="margin-top: 15px;">
                    {% if employees %}
                        {% for emp in employees %}
                            <li>
                                <div>
                                    <strong style="font-size: 16px;">{{ emp[0] }}</strong> 
                                    <span style="color: #666; font-size: 13px; margin-left: 15px;">(到職日: {{ emp[1] if emp[1] else '未設定' }})</span>
                                    <span style="color: #007bff; font-size: 13px; margin-left: 15px; font-weight: bold;">
                                        法定特休總天數: {{ emp[2] }} 天 | 累計已休: {{ emp[3] }} 天 | 剩餘: {{ emp[2] - emp[3] }} 天
                                    </span>
                                </div>
                                <form action="/admin/employee/delete" method="POST" style="margin:0;">
                                    <input type="hidden" name="emp_name" value="{{ emp[0] }}">
                                    <button type="submit" class="danger" style="padding:4px 10px; font-size:12px; margin:0; width:auto;" onclick="return confirm('確定要刪除員工 {{ emp[0] }} 嗎？');">刪除</button>
                                </form>
                            </li>
                        {% endfor %}
                    {% else %}
                        <li style="background: transparent; color: #888; justify-content: center;">目前名單中尚無員工。</li>
                    {% endif %}
                </ul>
            </div>

            <!-- 月份結算報表 -->
            <div class="section">
                <h3>📊 {{ selected_month }} 月份出勤與排休結算</h3>
                <table>
                    <tr>
                        <th>員工姓名</th>
                        <th>結算月份</th>
                        <th>實際上班</th>
                        <th>排休天數</th>
                        <th>曠工天數</th>
                        <th>各假別統計 (特/病/事/婚/喪/陪/產/其他)</th>
                    </tr>
                    {% for stat in monthly_stats %}
                    <tr>
                        <td><strong>{{ stat.name }}</strong></td>
                        <td>{{ selected_month }}</td>
                        <td><span style="color: #28a745; font-weight: bold; font-size: 15px;">{{ stat.work_days }} 天</span></td>
                        <td><span style="color: #17a2b8; font-weight: bold; font-size: 15px;">{{ stat.off_days }} 天</span></td>
                        <td>
                            {% if stat.absent_days > 0 %}
                                <span style="color: #dc3545; font-weight: bold; font-size: 15px;">{{ stat.absent_days }} 天</span>
                                <div style="font-size: 11px; color: #dc3545; margin-top: 4px;">({{ stat.absent_dates | join(', ') }})</div>
                            {% else %}
                                <span style="color: #6c757d;">0 天</span>
                            {% endif %}
                        </td>
                        <td style="text-align: left; padding-left: 15px;">
                            特休: <span style="color: #d9534f; font-weight: bold;">{{ stat.leaves.get('特', 0) }}</span> 天 | 
                            病假: {{ stat.leaves.get('病', 0) }} 天 | 
                            事假: {{ stat.leaves.get('事', 0) }} 天 | 
                            婚假: {{ stat.leaves.get('婚', 0) }} 天 | 
                            喪假: {{ stat.leaves.get('喪', 0) }} 天 | 
                            陪產: {{ stat.leaves.get('陪', 0) }} 天 | 
                            產假: {{ stat.leaves.get('產', 0) }} 天 | 
                            其他: {{ stat.leaves.get('其他', 0) }} 天
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>

            <!-- 當月排休設定與清單 -->
            <div class="section">
                <h3>🗓️ 安排員工排休假 (目前顯示 {{ selected_month }} 當月紀錄)</h3>
                <form method="POST" action="/admin/schedule" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <select name="emp_name" required style="flex: 1; margin: 0; min-width: 150px;">
                        <option
