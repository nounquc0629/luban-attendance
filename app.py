import os
import calendar
import datetime
import psycopg2
from flask import Flask, request, render_template_string, redirect, url_for, session

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

            if (!confirm(confirmMsg)) {
                return;
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
                        <option value="" disabled selected>-- 選擇排休員工 --</option>
                        {% for emp in employees %}
                            <option value="{{ emp[0] }}">{{ emp[0] }}</option>
                        {% endfor %}
                    </select>
                    <input type="date" name="off_date" required style="margin: 0;">
                    <button type="submit" style="margin: 0; width: auto; padding: 10px 20px;">新增排休</button>
                </form>

                <table style="margin-top: 15px;">
                    <tr>
                        <th>員工姓名</th>
                        <th>排休日期</th>
                        <th>操作</th>
                    </tr>
                    {% for sch in schedules %}
                    <tr>
                        <td>{{ sch[1] }}</td>
                        <td>{{ sch[2] }}</td>
                        <td>
                            <form action="/admin/schedule/delete" method="POST" style="margin:0; display:inline;">
                                <input type="hidden" name="schedule_id" value="{{ sch[0] }}">
                                <button type="submit" class="danger" style="padding:4px 10px; font-size:12px; margin:0; width:auto;" onclick="return confirm('確定要取消此排休嗎？');">取消排休</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not schedules %}
                    <tr>
                        <td colspan="3" style="color: #888;">此月份尚無任何排休設定。</td>
                    </tr>
                    {% endif %}
                </table>
            </div>

            <!-- 打卡與請假明細紀錄表格 (含修改按鈕) -->
            <div class="section">
                <h3>📋 {{ selected_month }} 月打卡與請假明細紀錄</h3>
                <table>
                    <tr>
                        <th>編號</th>
                        <th>員工姓名</th>
                        <th>狀態</th>
                        <th>請假代號</th>
                        <th>打卡時間 (台灣時間)</th>
                        <th>IP 位址</th>
                        <th>操作</th>
                    </tr>
                    {% for rec in records %}
                    <tr>
                        <td>{{ rec[0] }}</td>
                        <td>{{ rec[1] }}</td>
                        <td>
                            {% if rec[2] == '上班' %}
                                <span style="color:#28a745; font-weight:bold;">上班</span>
                            {% elif rec[2] == '下班' %}
                                <span style="color:#dc3545; font-weight:bold;">下班</span>
                            {% else %}
                                <span style="color:#fd7e14; font-weight:bold;">請假</span>
                            {% endif %}
                        </td>
                        <td>{{ rec[3] if rec[3] else '-' }}</td>
                        <td>{{ rec[4].strftime('%Y-%m-%d %H:%M:%S') }}</td>
                        <td>{{ rec[5] }}</td>
                        <td>
                            <!-- 修改按鈕 -->
                            <button type="button" class="edit-btn" style="padding:4px 8px; font-size:12px; margin:0 2px; width:auto;"
                                    onclick="openEditModal('{{ rec[0] }}', '{{ rec[1] }}', '{{ rec[2] }}', '{{ rec[3] or '' }}', '{{ rec[4].strftime('%Y-%m-%dT%H:%M') }}')">
                                修改
                            </button>
                            
                            <!-- 刪除按鈕 -->
                            <form action="/admin/record/delete" method="POST" style="display:inline; margin:0;">
                                <input type="hidden" name="record_id" value="{{ rec[0] }}">
                                <button type="submit" class="danger" style="padding:4px 8px; font-size:12px; margin:0 2px; width:auto;" onclick="return confirm('確定要刪除此筆打卡紀錄嗎？');">刪除</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not records %}
                    <tr>
                        <td colspan="7" style="color: #888;">此月份尚無任何打卡紀錄。</td>
                    </tr>
                    {% endif %}
                </table>
            </div>

            <!-- 修改打卡彈跳視窗 (Modal) -->
            <div id="editModal" class="modal">
                <div class="modal-content">
                    <div class="modal-header">✏️ 修改打卡 / 請假紀錄</div>
                    <form method="POST" action="/admin/record/edit">
                        <div class="modal-body">
                            <input type="hidden" name="record_id" id="modal-record-id">
                            
                            <label>員工姓名：</label>
                            <input type="text" id="modal-emp-name" readonly style="background-color: #eee;">

                            <label>狀態 (動作)：</label>
                            <select name="action" id="modal-action" required onchange="toggleLeaveField()">
                                <option value="上班">上班</option>
                                <option value="下班">下班</option>
                                <option value="請假">請假</option>
                            </select>

                            <div id="modal-leave-group">
                                <label>請假代號：</label>
                                <select name="leave_code" id="modal-leave-code">
                                    <option value="">-- 無 --</option>
                                    <option value="特">特休假 (有薪)</option>
                                    <option value="病">普通傷病假 (半薪)</option>
                                    <option value="事">事假 (無薪)</option>
                                    <option value="婚">婚假 (有薪)</option>
                                    <option value="喪">喪假 (有薪)</option>
                                    <option value="陪">陪產假 (有薪)</option>
                                    <option value="產">產假/產檢假 (有薪)</option>
                                    <option value="其他">其他</option>
                                </select>
                            </div>

                            <label>打卡時間：</label>
                            <input type="datetime-local" name="timestamp" id="modal-timestamp" required>
                        </div>
                        <div class="modal-footer">
                            <button type="button" style="background-color: #6c757d; margin:0 5px;" onclick="closeEditModal()">取消</button>
                            <button type="submit" style="background-color: #28a745; margin:0 5px;">儲存修改</button>
                        </div>
                    </form>
                </div>
            </div>

            <script>
                function openEditModal(id, name, action, leaveCode, timestampStr) {
                    document.getElementById('modal-record-id').value = id;
                    document.getElementById('modal-emp-name').value = name;
                    document.getElementById('modal-action').value = action;
                    document.getElementById('modal-leave-code').value = leaveCode;
                    document.getElementById('modal-timestamp').value = timestampStr;
                    
                    toggleLeaveField();
                    document.getElementById('editModal').style.display = 'block';
                }

                function closeEditModal() {
                    document.getElementById('editModal').style.display = 'none';
                }

                function toggleLeaveField() {
                    const action = document.getElementById('modal-action').value;
                    const leaveGroup = document.getElementById('modal-leave-group');
                    if (action === '請假') {
                        leaveGroup.style.display = 'block';
                    } else {
                        leaveGroup.style.display = 'none';
                        document.getElementById('modal-leave-code').value = '';
                    }
                }

                window.onclick = function(event) {
                    const modal = document.getElementById('editModal');
                    if (event.target == modal) {
                        closeEditModal();
                    }
                }
            </script>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    init_db()
    message = None
    success = False

    conn = get_db_connection()
    c = conn.cursor()

    if request.method == 'POST':
        emp_name = request.form.get('emp_name')
        action = request.form.get('action')
        leave_code = request.form.get('leave_code') if action == '請假' else None
        
        # 取得 client IP
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        else:
            ip_address = request.remote_addr

        # 台灣時區時間 (UTC+8)
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)

        if emp_name and action:
            c.execute(
                "INSERT INTO records (emp_name, action, leave_code, timestamp, ip_address) VALUES (%s, %s, %s, %s, %s)",
                (emp_name, action, leave_code, now, ip_address)
            )
            conn.commit()
            success = True
            if action == '請假':
                message = f"✅ 【{emp_name}】請假申請（{leave_code}）已成功送出！"
            else:
                message = f"✅ 【{emp_name}】{action}打卡成功！時間：{now.strftime('%H:%M:%S')}"

    # 取得員工列表
    c.execute("SELECT name FROM employees ORDER BY id ASC")
    employees = c.fetchall()
    c.close()
    conn.close()

    return render_template_string(
        HTML_TEMPLATE,
        employees=employees,
        message=message,
        success=success,
        store_lat=STORE_LAT,
        store_lng=STORE_LNG,
        max_dist=MAX_DISTANCE_METERS
    )

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    init_db()
    today_dt = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    today_str = today_dt.strftime('%Y-%m-%d')
    selected_month = request.args.get('month', today_dt.strftime('%Y-%m'))

    error = None
    msg = None

    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
        else:
            error = "密碼錯誤，請重新輸入！"

    logged_in = session.get('admin_logged_in', False)
    if not logged_in:
        return render_template_string(ADMIN_TEMPLATE, logged_in=False, error=error)

    # 計算月份起始與結束時間
    year, month = map(int, selected_month.split('-'))
    last_day = calendar.monthrange(year, month)[1]
    start_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, last_day)
    start_datetime = datetime.datetime(year, month, 1, 0, 0, 0)
    end_datetime = datetime.datetime(year, month, last_day, 23, 59, 59)

    conn = get_db_connection()
    c = conn.cursor()

    # 1. 取得員工列表與特休計算
    c.execute("SELECT name, hire_date FROM employees ORDER BY id ASC")
    raw_employees = c.fetchall()
    employees = []
    for emp in raw_employees:
        name = emp[0]
        hire_date = emp[1]
        annual_quota = calculate_annual_leave(hire_date)
        
        # 累計已休特休天數
        c.execute("""
            SELECT COUNT(DISTINCT DATE(timestamp)) 
            FROM records 
            WHERE emp_name = %s AND action = '請假' AND leave_code = '特'
        """, (name,))
        used_annual = c.fetchone()[0] or 0
        employees.append((name, hire_date, annual_quota, used_annual))

    # 2. 月份出勤與排休結算
    monthly_stats = []
    for emp in raw_employees:
        name = emp[0]
        # 實際上班天數
        c.execute("""
            SELECT COUNT(DISTINCT DATE(timestamp)) 
            FROM records 
            WHERE emp_name = %s AND action = '上班' AND timestamp BETWEEN %s AND %s
        """, (name, start_datetime, end_datetime))
        work_days = c.fetchone()[0] or 0

        # 當月排休天數與日期
        c.execute("""
            SELECT off_date FROM schedules 
            WHERE emp_name = %s AND off_date BETWEEN %s AND %s
        """, (name, start_date, end_date))
        off_records = c.fetchall()
        off_days = len(off_records)
        off_dates = {sch[0] for sch in off_records}

        # 當月各假別統計
        c.execute("""
            SELECT leave_code, COUNT(DISTINCT DATE(timestamp)) 
            FROM records 
            WHERE emp_name = %s AND action = '請假' AND timestamp BETWEEN %s AND %s
            GROUP BY leave_code
        """, (name, start_datetime, end_datetime))
        leave_counts = {row[0]: row[1] for row in c.fetchall()}

        # 曠工天數計算 (至今為止未上班、未排休、未請假的日子)
        limit_date = min(today_dt.date(), end_date)
        absent_dates = []
        if limit_date >= start_date:
            c.execute("""
                SELECT DISTINCT DATE(timestamp) 
                FROM records 
                WHERE emp_name = %s AND timestamp BETWEEN %s AND %s
            """, (name, start_datetime, datetime.datetime.combine(limit_date, datetime.time.max)))
            active_dates = {row[0] for row in c.fetchall()}

            current = start_date
            while current <= limit_date:
                if current not in off_dates and current not in active_dates:
                    absent_dates.append(current.strftime('%m-%d'))
                current += datetime.timedelta(days=1)

        monthly_stats.append({
            'name': name,
            'work_days': work_days,
            'off_days': off_days,
            'absent_days': len(absent_dates),
            'absent_dates': absent_dates,
            'leaves': leave_counts
        })

    # 3. 當月排休清單
    c.execute("""
        SELECT id, emp_name, off_date 
        FROM schedules 
        WHERE off_date BETWEEN %s AND %s 
        ORDER BY off_date DESC
    """, (start_date, end_date))
    schedules = c.fetchall()

    # 4. 當月打卡明細紀錄
    c.execute("""
        SELECT id, emp_name, action, leave_code, timestamp, ip_address 
        FROM records 
        WHERE timestamp BETWEEN %s AND %s 
        ORDER BY timestamp DESC
    """, (start_datetime, end_datetime))
    records = c.fetchall()

    c.close()
    conn.close()

    return render_template_string(
        ADMIN_TEMPLATE,
        logged_in=True,
        db_status="PostgreSQL 資料庫連線正常",
        msg=msg,
        error=error,
        selected_month=selected_month,
        today_str=today_str,
        employees=employees,
        monthly_stats=monthly_stats,
        schedules=schedules,
        records=records
    )

# 新增員工
@app.route('/admin/employee', methods=['POST'])
def add_employee():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    emp_name = request.form.get('new_emp_name', '').strip()
    hire_date = request.form.get('hire_date')
    if emp_name:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO employees (name, hire_date) VALUES (%s, %s)", (emp_name, hire_date or None))
        conn.commit()
        c.close()
        conn.close()
    return redirect(request.referrer or url_for('admin'))

# 刪除員工
@app.route('/admin/employee/delete', methods=['POST'])
def delete_employee():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    emp_name = request.form.get('emp_name')
    if emp_name:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM employees WHERE name = %s", (emp_name,))
        conn.commit()
        c.close()
        conn.close()
    return redirect(request.referrer or url_for('admin'))

# 新增排休
@app.route('/admin/schedule', methods=['POST'])
def add_schedule():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    emp_name = request.form.get('emp_name')
    off_date = request.form.get('off_date')
    if emp_name and off_date:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO schedules (emp_name, off_date) VALUES (%s, %s)", (emp_name, off_date))
        conn.commit()
        c.close()
        conn.close()
    return redirect(request.referrer or url_for('admin'))

# 取消排休
@app.route('/admin/schedule/delete', methods=['POST'])
def delete_schedule():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    schedule_id = request.form.get('schedule_id')
    if schedule_id:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM schedules WHERE id = %s", (schedule_id,))
        conn.commit()
        c.close()
        conn.close()
    return redirect(request.referrer or url_for('admin'))

# 刪除打卡紀錄
@app.route('/admin/record/delete', methods=['POST'])
def delete_record():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    record_id = request.form.get('record_id')
    if record_id:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM records WHERE id = %s", (record_id,))
        conn.commit()
        c.close()
        conn.close()
    return redirect(request.referrer or url_for('admin'))

# 修改打卡紀錄 (新增)
@app.route('/admin/record/edit', methods=['POST'])
def edit_record():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    
    record_id = request.form.get('record_id')
    action = request.form.get('action')
    leave_code = request.form.get('leave_code') if action == '請假' else None
    timestamp_str = request.form.get('timestamp')
    
    if record_id and action and timestamp_str:
        try:
            new_timestamp = datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M")
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("""
                UPDATE records 
                SET action = %s, leave_code = %s, timestamp = %s 
                WHERE id = %s
            """, (action, leave_code, new_timestamp, record_id))
            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            print(f"修改紀錄失敗: {e}")
            
    return redirect(request.referrer or url_for('admin'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
