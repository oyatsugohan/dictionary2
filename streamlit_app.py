import streamlit as st
import json
import sqlite3
import hashlib
import base64
from datetime import datetime
from io import BytesIO
from PIL import Image
import os
import re

# DBファイルのパスを確実に固定する
# 環境変数 ENCYCLOPEDIA_DB_PATH が設定されていればそれを使用、なければスクリプトと同じフォルダ
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
DB_FILE = os.environ.get("ENCYCLOPEDIA_DB_PATH", os.path.join(_SCRIPT_DIR, "encyclopedia.db"))
# 起動時にパスをターミナルに表示（確認用）
print(f"📂 DB保存先: {os.path.abspath(DB_FILE)}")

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                created TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                content TEXT,
                images TEXT,
                created TEXT NOT NULL,
                updated TEXT,
                FOREIGN KEY (username) REFERENCES users(username),
                UNIQUE(username, title)
            )
        ''')
        conn.commit()
        print(f"✅ データベース初期化成功: {os.path.abspath(DB_FILE)}")
        return conn
    except Exception as e:
        print(f"❌ データベース初期化エラー: {e}")
        st.error(f"データベース初期化エラー: {e}")
        return None

def get_db_connection():
    try:
        if "db_conn" in st.session_state and st.session_state.db_conn is not None:
            try:
                st.session_state.db_conn.execute("SELECT 1")
                return st.session_state.db_conn
            except Exception as e:
                print(f"⚠️ 既存の接続が無効: {e}")
                try:
                    st.session_state.db_conn.close()
                except:
                    pass
        st.session_state.db_conn = init_db()
        return st.session_state.db_conn
    except Exception as e:
        print(f"❌ データベース接続エラー: {e}")
        st.error(f"データベース接続エラー: {e}")
        return None

def hash_password(password, username=None):
    if username:
        salted = f"{username}:{password}"
    else:
        salted = password
    return hashlib.sha256(salted.encode()).hexdigest()

def encode_image(image_file):
    if image_file is not None:
        img = Image.open(image_file)
        max_width = 1920
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        buffered = BytesIO()
        img_format = img.format if img.format else 'PNG'
        if img_format == 'JPEG':
            img.save(buffered, format=img_format, quality=98, optimize=True)
        else:
            img.save(buffered, format=img_format, optimize=True)
        return base64.b64encode(buffered.getvalue()).decode()
    return None

def decode_image(base64_string):
    if base64_string:
        return Image.open(BytesIO(base64.b64decode(base64_string)))
    return None

def render_markers_to_html(text):
    text = re.sub(r'<yellow>(.*?)</yellow>', 
                  r'<mark style="background-color: #ffeb3b; padding: 2px 4px; border-radius: 3px;">\1</mark>', 
                  text, flags=re.DOTALL)
    text = re.sub(r'<green>(.*?)</green>', 
                  r'<mark style="background-color: #8bc34a; padding: 2px 4px; border-radius: 3px;">\1</mark>', 
                  text, flags=re.DOTALL)
    text = re.sub(r'<blue>(.*?)</blue>', 
                  r'<mark style="background-color: #03a9f4; color: white; padding: 2px 4px; border-radius: 3px;">\1</mark>', 
                  text, flags=re.DOTALL)
    text = re.sub(r'<red>(.*?)</red>', 
                  r'<mark style="background-color: #f44336; color: white; padding: 2px 4px; border-radius: 3px;">\1</mark>', 
                  text, flags=re.DOTALL)
    text = text.replace('\n', '<br>')
    return text

def create_article_links(content, all_titles, current_title):
    linked_content = content
    sorted_titles = sorted([t for t in all_titles if t != current_title], key=len, reverse=True)
    for title in sorted_titles:
        if title in linked_content:
            linked_content = linked_content.replace(title, f"<strong>{title}</strong>")
    linked_content = render_markers_to_html(linked_content)
    return linked_content

def register_user(username, password):
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (username, password, created)
            VALUES (?, ?, ?)
        ''', (username, hash_password(password, username), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        st.error(f"ユーザー登録エラー: {e}")
        return False

def authenticate_user(username, password):
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        c = conn.cursor()
        c.execute('SELECT password FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        if not result:
            return False

        stored_hash = result[0]

        # 新方式（ソルトあり）で照合
        if stored_hash == hash_password(password, username):
            return True

        # 旧方式（ソルトなし）で照合 → 一致したら新方式に自動移行
        if stored_hash == hash_password(password, username=None):
            new_hash = hash_password(password, username)
            c.execute('UPDATE users SET password = ? WHERE username = ?', (new_hash, username))
            conn.commit()
            print(f"🔄 パスワードを新方式に移行しました: {username}")
            return True

        return False
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return False

def get_user_encyclopedia(username):
    conn = get_db_connection()
    if conn is None:
        return {}
    try:
        c = conn.cursor()
        c.execute('''
            SELECT title, category, content, images, created, updated
            FROM articles
            WHERE username = ?
        ''', (username,))
        encyclopedia = {}
        for row in c.fetchall():
            title, category, content, images, created, updated = row
            encyclopedia[title] = {
                "category": json.loads(category) if category else ["未分類"],
                "content": content,
                "images": json.loads(images) if images else [],
                "created": created,
                "updated": updated
            }
        return encyclopedia
    except Exception as e:
        st.error(f"記事取得エラー: {e}")
        return {}

def save_article(username, title, category, content, images, created=None, updated=None):
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        c = conn.cursor()
        category_json = json.dumps(category, ensure_ascii=False)
        images_json = json.dumps(images, ensure_ascii=False) if images else None
        if created is None:
            created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            c.execute('''
                INSERT INTO articles (username, title, category, content, images, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (username, title, category_json, content, images_json, created, updated))
        except sqlite3.IntegrityError:
            c.execute('''
                UPDATE articles
                SET category = ?, content = ?, images = ?, updated = ?
                WHERE username = ? AND title = ?
            ''', (category_json, content, images_json, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, title))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"記事保存エラー: {e}")
        return False

def delete_article(username, title):
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        c = conn.cursor()
        c.execute('DELETE FROM articles WHERE username = ? AND title = ?', (username, title))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"記事削除エラー: {e}")
        return False

def backup_database():
    if os.path.exists(DB_FILE):
        backup_file = os.path.expanduser(f"~/encyclopedia_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        import shutil
        shutil.copy(DB_FILE, backup_file)
        return backup_file
    return None

def find_backup_files():
    home_dir = os.path.expanduser("~")
    backup_files = []
    try:
        for file in os.listdir(home_dir):
            if file.startswith("encyclopedia_backup_") and file.endswith(".db"):
                full_path = os.path.join(home_dir, file)
                backup_files.append({
                    "name": file,
                    "path": full_path,
                    "size": os.path.getsize(full_path),
                    "modified": datetime.fromtimestamp(os.path.getmtime(full_path))
                })
        return sorted(backup_files, key=lambda x: x["modified"], reverse=True)
    except Exception as e:
        return []

def restore_from_backup(backup_path):
    try:
        import shutil
        if os.path.exists(DB_FILE):
            temp_backup = os.path.expanduser(f"~/encyclopedia_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            shutil.copy(DB_FILE, temp_backup)
        shutil.copy(backup_path, DB_FILE)
        if "db_conn" in st.session_state:
            try:
                st.session_state.db_conn.close()
            except:
                pass
            del st.session_state.db_conn
        return True
    except Exception as e:
        st.error(f"復元エラー: {e}")
        return False

# アプリの設定
st.set_page_config(page_title="オリジナル百科事典", page_icon="📚", layout="wide")

st.markdown("""
<style>
    .marker-buttons {
        display: flex;
        gap: 10px;
        margin-bottom: 10px;
    }
    .marker-btn {
        padding: 5px 15px;
        border-radius: 5px;
        border: none;
        cursor: pointer;
        font-weight: bold;
    }
    .yellow-btn { background-color: #ffeb3b; }
    .green-btn { background-color: #8bc34a; }
    .blue-btn { background-color: #03a9f4; color: white; }
    .red-btn { background-color: #f44336; color: white; }
    [data-testid="column"] img {
        max-width: 200px;
        height: auto;
    }
    [data-testid="StyledFullScreenFrame"] img {
        max-width: 100% !important;
        width: auto !important;
        height: auto !important;
    }
</style>
""", unsafe_allow_html=True)

if "db_initialized" not in st.session_state:
    conn = init_db()
    if conn:
        st.session_state.db_conn = conn
        st.session_state.db_initialized = True

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "encyclopedia" not in st.session_state:
    st.session_state.encyclopedia = {}
if "selected_article" not in st.session_state:
    st.session_state.selected_article = None

if not st.session_state.logged_in:
    st.title("📚 オリジナル百科事典")
    st.markdown("---")

    # ② expander を廃止（"arrive right/down" 文字化け対策）
    db_abs_path = os.path.abspath(DB_FILE)
    st.markdown("#### ℹ️ システム情報")
    st.info(f"**データベースの保存場所**: `{db_abs_path}`")
    if os.path.exists(DB_FILE):
        file_size = os.path.getsize(DB_FILE) / 1024
        st.success(f"✅ データベースが見つかりました（サイズ: {file_size:.2f} KB）　💾 データは永続的に保存されます！")
    else:
        st.warning("⚠️ データベースファイルが見つかりません。ログイン後に自動作成されます。")

    backup_files = find_backup_files()
    if backup_files:
        st.markdown("---")
        st.success(f"🔍 **{len(backup_files)}件のバックアップファイルが見つかりました**")
        selected_backup = st.selectbox(
            "復元するバックアップを選択（任意）",
            options=["復元しない"] + [f"{b['name']} ({b['modified'].strftime('%Y-%m-%d %H:%M:%S')}, {b['size']/1024:.2f} KB)" for b in backup_files],
            key="backup_selector"
        )
        if selected_backup != "復元しない":
            backup_idx = [f"{b['name']} ({b['modified'].strftime('%Y-%m-%d %H:%M:%S')}, {b['size']/1024:.2f} KB)" for b in backup_files].index(selected_backup)
            selected_backup_path = backup_files[backup_idx]["path"]
            st.warning(f"⚠️ 「{backup_files[backup_idx]['name']}」から復元しますか？")
            st.caption("現在のデータベースは自動的にバックアップされます。")
            if st.button("🔄 復元を実行", type="primary"):
                if restore_from_backup(selected_backup_path):
                    st.success("✅ 復元が完了しました！ページを再読み込みしてください。")
                    st.balloons()
                    st.rerun()
                else:
                    st.error("復元に失敗しました。")

    tab1, tab2 = st.tabs(["🔐 ログイン", "✍️ 新規登録"])

    with tab1:
        st.header("ログイン")
        with st.form("login_form"):
            username = st.text_input("ユーザー名")
            password = st.text_input("パスワード", type="password")
            login_button = st.form_submit_button("ログイン")
            if login_button:
                if authenticate_user(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.encyclopedia = get_user_encyclopedia(username)
                    st.success(f"ようこそ、{username}さん！")
                    st.rerun()
                else:
                    st.error("ユーザー名またはパスワードが間違っています")

    with tab2:
        st.header("新規登録")
        with st.form("signup_form"):
            new_username = st.text_input("ユーザー名（半角英数字推奨）")
            new_password = st.text_input("パスワード", type="password")
            confirm_password = st.text_input("パスワード（確認）", type="password")
            signup_button = st.form_submit_button("登録")
            if signup_button:
                if not new_username or not new_password:
                    st.error("ユーザー名とパスワードを入力してください")
                elif new_password != confirm_password:
                    st.error("パスワードが一致しません")
                elif len(new_password) < 4:
                    st.error("パスワードは4文字以上で設定してください")
                else:
                    if register_user(new_username, new_password):
                        st.success("登録が完了しました！ログインしてください。")
                    else:
                        st.error("このユーザー名は既に使用されています")

else:
    # ログイン後のメイン画面

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.title(f"📚 {st.session_state.username}の百科事典")
    with col2:
        if st.button("💾 バックアップ"):
            backup_file = backup_database()
            if backup_file:
                st.success(f"バックアップ完了！")
                st.caption(os.path.basename(backup_file))
    with col3:
        if st.button("🚪 ログアウト"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.encyclopedia = {}
            st.rerun()

    st.markdown("---")

    # ★ アプリ紹介バナー ★
    st.info(
        "📖 このアプリは **自分だけの百科事典** を作れる「オリジナル百科事典」です！　"
        "気になることや覚えておきたいことを記事としてまとめ、画像やカラーマーカーで自由にカスタマイズできます。"
        "まずは左のメニューから ➕ **新規記事作成** を試してみましょう！"
    )

    st.markdown("---")

    with st.sidebar:
        st.header("メニュー")
        menu = st.radio("機能を選択", ["🔍 記事を検索", "➕ 新規記事作成", "📝 記事を編集", "🗑️ 記事を削除", "📊 統計情報"])
        st.markdown("---")
        st.markdown("**💾 データベース情報**")
        st.caption(f"保存先: {os.path.abspath(DB_FILE)}")
        if os.path.exists(DB_FILE):
            file_size = os.path.getsize(DB_FILE) / 1024
            st.caption(f"サイズ: {file_size:.2f} KB　✅ 保存済み")
        show_list = st.checkbox("📖 登録済み記事一覧を表示", value=True)
        if show_list:
            st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
            if st.session_state.encyclopedia:
                for title in sorted(st.session_state.encyclopedia.keys()):
                    st.text(f"• {title}")
            else:
                st.info("まだ記事がありません")

    if menu == "🔍 記事を検索":
        st.header("記事を検索")
        st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
        if st.session_state.encyclopedia:
            all_categories = set()
            for article in st.session_state.encyclopedia.values():
                cats = article.get("category", ["未分類"])
                if isinstance(cats, list):
                    all_categories.update(cats)
                else:
                    all_categories.add(cats)
            all_categories = sorted(all_categories)
            col1, col2 = st.columns(2)
            with col1:
                search_term = st.text_input("🔎 検索キーワードを入力", placeholder="記事のタイトルで検索")
            with col2:
                selected_category = st.selectbox("🏷️ カテゴリーで絞り込み", ["すべて"] + all_categories)
            results = st.session_state.encyclopedia.copy()
            if search_term:
                results = {k: v for k, v in results.items() if search_term.lower() in k.lower()}
            if selected_category != "すべて":
                results = {k: v for k, v in results.items() 
                          if selected_category in (v.get("category", ["未分類"]) if isinstance(v.get("category", []), list) else [v.get("category", "未分類")])}
            if results:
                st.success(f"{len(results)}件の記事が見つかりました")
                st.markdown("### 📋 記事一覧")
                cols = st.columns(3)
                for idx, title in enumerate(sorted(results.keys())):
                    with cols[idx % 3]:
                        if st.button(f"📄 {title}", key=f"article_btn_{title}", use_container_width=True):
                            st.session_state.selected_article = title
                if st.session_state.selected_article and st.session_state.selected_article in st.session_state.encyclopedia:
                    st.markdown("---")
                    st.markdown(f"## 📖 {st.session_state.selected_article}")
                    content = st.session_state.encyclopedia[st.session_state.selected_article]
                    cats = content.get('category', ['未分類'])
                    if isinstance(cats, list):
                        category_display = ", ".join(cats)
                    else:
                        category_display = cats
                    st.markdown(f"**カテゴリー:** {category_display}")
                    st.markdown(f"**作成日:** {content.get('created', '不明')}")
                    if content.get('updated'):
                        st.markdown(f"**更新日:** {content.get('updated')}")
                    images = content.get('images', [])
                    if images:
                        st.markdown("**📷 画像:**")
                        img_cols = st.columns(min(len(images), 3))
                        for idx, img_data in enumerate(images):
                            img = decode_image(img_data)
                            if img:
                                with img_cols[idx % 3]:
                                    st.image(img, caption=f"画像 {idx + 1}")
                    st.markdown("---")
                    article_content = content.get('content', '')
                    all_titles = list(st.session_state.encyclopedia.keys())
                    st.markdown("### 本文")
                    linked_content = create_article_links(article_content, all_titles, st.session_state.selected_article)
                    st.markdown(linked_content, unsafe_allow_html=True)
                    st.markdown("---")
                    st.markdown("### 🔗 本文中で言及されている記事")
                    mentioned_articles = [t for t in all_titles if t != st.session_state.selected_article and t in article_content]
                    if mentioned_articles:
                        link_cols = st.columns(min(len(mentioned_articles), 4))
                        for idx, mentioned_title in enumerate(mentioned_articles):
                            with link_cols[idx % len(link_cols)]:
                                if st.button(f"➡️ {mentioned_title}", key=f"link_{mentioned_title}", use_container_width=True):
                                    st.session_state.selected_article = mentioned_title
                                    st.rerun()
                    else:
                        st.info("この記事では他の記事への言及はありません")
            else:
                st.warning("該当する記事が見つかりませんでした")
        else:
            st.info("まだ記事がありません。「新規記事作成」から記事を追加してください。")

    elif menu == "➕ 新規記事作成":
        st.header("新規記事作成")
        title = st.text_input("📝 記事タイトル", placeholder="例: Python")
        category = st.text_input("🏷️ カテゴリー", placeholder="例: プログラミング言語, 技術 (カンマ区切りで複数指定可能)")
        uploaded_images = st.file_uploader("🖼️ 画像を追加（任意・複数選択可）", 
                                          type=['png', 'jpg', 'jpeg', 'gif', 'webp'],
                                          accept_multiple_files=True)
        if uploaded_images:
            st.write(f"**選択された画像: {len(uploaded_images)}枚**")
            preview_cols = st.columns(min(len(uploaded_images), 3))
            for idx, img_file in enumerate(uploaded_images):
                with preview_cols[idx % 3]:
                    st.image(img_file, caption=f"画像 {idx + 1}", width=150)
        st.markdown("### ✍️ 記事内容")
        st.markdown("**🖍️ マーカーを挿入:**")
        marker_col1, marker_col2, marker_col3, marker_col4 = st.columns(4)
        marker_instruction = ""
        with marker_col1:
            if st.button("🟨 黄色マーカー", use_container_width=True):
                marker_instruction = "\n\n**選択した文字を** `<yellow>文字</yellow>` **で囲んでください**"
        with marker_col2:
            if st.button("🟩 緑マーカー", use_container_width=True):
                marker_instruction = "\n\n**選択した文字を** `<green>文字</green>` **で囲んでください**"
        with marker_col3:
            if st.button("🟦 青マーカー", use_container_width=True):
                marker_instruction = "\n\n**選択した文字を** `<blue>文字</blue>` **で囲んでください**"
        with marker_col4:
            if st.button("🟥 赤マーカー", use_container_width=True):
                marker_instruction = "\n\n**選択した文字を** `<red>文字</red>` **で囲んでください**"
        if marker_instruction:
            st.info(marker_instruction)
        with st.expander("📖 マーカーの使い方詳細"):
            st.markdown("""
            文章中でマーカーを引きたい部分を以下のタグで囲んでください：
            
            **使い方:**
            - 黄色: `<yellow>重要な文字</yellow>`
            - 緑色: `<green>良い点</green>`
            - 青色: `<blue>注意点</blue>`
            - 赤色: `<red>警告</red>`
            """, unsafe_allow_html=False)
            example_text = "Pythonは<yellow>人気のプログラミング言語</yellow>です。<green>初心者にも優しく</green>、多くの用途があります。ただし<red>セキュリティには注意</red>が必要です。"
            st.markdown(render_markers_to_html(example_text), unsafe_allow_html=True)
        content = st.text_area("記事本文を入力", height=300, 
                              placeholder="記事の内容を入力してください...\n\nマーカーの使い方:\n<yellow>黄色</yellow>\n<green>緑</green>\n<blue>青</blue>\n<red>赤</red>",
                              key="new_content")
        if content:
            st.markdown("---")
            st.markdown("### 👁️ プレビュー")
            preview_content = render_markers_to_html(content)
            st.markdown(preview_content, unsafe_allow_html=True)
        if st.button("✅ 記事を保存", type="primary", use_container_width=True):
            if not title:
                st.error("タイトルを入力してください")
            elif title in st.session_state.encyclopedia:
                st.error("同じタイトルの記事が既に存在します")
            elif not content:
                st.error("記事内容を入力してください")
            else:
                categories = [cat.strip() for cat in category.split(",") if cat.strip()]
                if not categories:
                    categories = ["未分類"]
                images_data = []
                if uploaded_images:
                    for img_file in uploaded_images:
                        img_file.seek(0)
                        encoded = encode_image(img_file)
                        if encoded:
                            images_data.append(encoded)
                if save_article(st.session_state.username, title, categories, content, images_data):
                    st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
                    st.success(f"✅ 記事「{title}」を保存しました！")
                    st.balloons()
                else:
                    st.error("記事の保存に失敗しました")

    elif menu == "📝 記事を編集":
        st.header("記事を編集")
        st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
        if st.session_state.encyclopedia:
            col1, col2 = st.columns(2)
            with col1:
                search_edit = st.text_input("🔎 記事を検索", placeholder="記事のタイトルで絞り込み", key="search_edit")
            with col2:
                all_categories = set()
                for article in st.session_state.encyclopedia.values():
                    cats = article.get("category", ["未分類"])
                    if isinstance(cats, list):
                        all_categories.update(cats)
                    else:
                        all_categories.add(cats)
                category_filter = st.selectbox("🏷️ カテゴリーで絞り込み", ["すべて"] + sorted(all_categories), key="category_edit")
            filtered_articles = list(st.session_state.encyclopedia.keys())
            if search_edit:
                filtered_articles = [k for k in filtered_articles if search_edit.lower() in k.lower()]
            if category_filter != "すべて":
                filtered_articles = [k for k in filtered_articles
                                   if category_filter in (st.session_state.encyclopedia[k].get("category", ["未分類"]) 
                                   if isinstance(st.session_state.encyclopedia[k].get("category", []), list) 
                                   else [st.session_state.encyclopedia[k].get("category", "未分類")])]
            if not filtered_articles:
                st.warning("該当する記事が見つかりませんでした")
            else:
                if search_edit or category_filter != "すべて":
                    st.success(f"{len(filtered_articles)}件の記事が見つかりました")
                article_to_edit = st.selectbox("編集する記事を選択", sorted(filtered_articles), key="article_selector")
                if article_to_edit:
                    current_data = st.session_state.encyclopedia[article_to_edit]
                    current_categories = current_data.get("category", [])
                    if isinstance(current_categories, list):
                        category_str = ", ".join(current_categories)
                    else:
                        category_str = current_categories
                    st.markdown("---")
                    st.subheader(f"📝 「{article_to_edit}」を編集中")
                    st.markdown("---")
                    new_title = st.text_input("📝 記事タイトル", value=article_to_edit, key=f"title_{article_to_edit}")
                    new_category = st.text_input("🏷️ カテゴリー", value=category_str, placeholder="カンマ区切りで複数指定可能", key=f"category_{article_to_edit}")
                    existing_images = current_data.get('images', [])
                    delete_key = f"images_to_delete_{article_to_edit}"
                    if delete_key not in st.session_state:
                        st.session_state[delete_key] = []
                    if existing_images:
                        st.markdown("### 🖼️ 現在の画像")
                        st.write(f"**登録済み画像: {len(existing_images)}枚**")
                        current_img_cols = st.columns(min(len(existing_images), 3))
                        for idx, img_data in enumerate(existing_images):
                            current_img = decode_image(img_data)
                            if current_img:
                                with current_img_cols[idx % 3]:
                                    st.image(current_img, caption=f"画像 {idx + 1}")
                                    delete_this = st.checkbox(
                                        f"🗑️ 削除", 
                                        key=f"delete_img_{article_to_edit}_{idx}",
                                        help=f"画像{idx + 1}を削除"
                                    )
                                    if delete_this and idx not in st.session_state[delete_key]:
                                        st.session_state[delete_key].append(idx)
                                    elif not delete_this and idx in st.session_state[delete_key]:
                                        st.session_state[delete_key].remove(idx)
                        if st.session_state[delete_key]:
                            st.warning(f"⚠️ {len(st.session_state[delete_key])}枚の画像が削除予定です")
                    st.markdown("---")
                    st.markdown("### ➕ 新しい画像を追加")
                    uploaded_images = st.file_uploader(
                        "🖼️ 画像を追加（複数選択可）", 
                        type=['png', 'jpg', 'jpeg', 'gif', 'webp'],
                        accept_multiple_files=True,
                        key=f"edit_images_{article_to_edit}",
                        help="既存の画像に追加されます"
                    )
                    if uploaded_images:
                        st.write(f"**追加する画像: {len(uploaded_images)}枚**")
                        new_img_cols = st.columns(min(len(uploaded_images), 3))
                        for idx, img_file in enumerate(uploaded_images):
                            with new_img_cols[idx % 3]:
                                st.image(img_file, caption=f"新しい画像 {idx + 1}")
                    delete_images = st.checkbox("🗑️ すべての画像を削除する", key=f"delete_img_{article_to_edit}")
                    st.markdown("### ✍️ 記事内容を編集")
                    st.markdown("**🖍️ マーカーを挿入:**")
                    edit_marker_col1, edit_marker_col2, edit_marker_col3, edit_marker_col4 = st.columns(4)
                    edit_marker_instruction = ""
                    with edit_marker_col1:
                        if st.button("🟨 黄色マーカー", use_container_width=True, key=f"edit_yellow_{article_to_edit}"):
                            edit_marker_instruction = "\n\n**選択した文字を** `<yellow>文字</yellow>` **で囲んでください**"
                    with edit_marker_col2:
                        if st.button("🟩 緑マーカー", use_container_width=True, key=f"edit_green_{article_to_edit}"):
                            edit_marker_instruction = "\n\n**選択した文字を** `<green>文字</green>` **で囲んでください**"
                    with edit_marker_col3:
                        if st.button("🟦 青マーカー", use_container_width=True, key=f"edit_blue_{article_to_edit}"):
                            edit_marker_instruction = "\n\n**選択した文字を** `<blue>文字</blue>` **で囲んでください**"
                    with edit_marker_col4:
                        if st.button("🟥 赤マーカー", use_container_width=True, key=f"edit_red_{article_to_edit}"):
                            edit_marker_instruction = "\n\n**選択した文字を** `<red>文字</red>` **で囲んでください**"
                    if edit_marker_instruction:
                        st.info(edit_marker_instruction)
                    new_content = st.text_area("記事本文", value=current_data.get("content", ""), height=300, key=f"edit_content_{article_to_edit}")
                    if new_content:
                        st.markdown("---")
                        st.markdown("### 👁️ プレビュー")
                        preview_content = render_markers_to_html(new_content)
                        st.markdown(preview_content, unsafe_allow_html=True)
                    if st.button("💾 更新を保存", type="primary", use_container_width=True, key=f"save_{article_to_edit}"):
                        if not new_title:
                            st.error("タイトルを入力してください")
                        elif not new_content:
                            st.error("記事内容を入力してください")
                        else:
                            categories = [cat.strip() for cat in new_category.split(",") if cat.strip()]
                            if not categories:
                                categories = ["未分類"]
                            existing_images_list = current_data.get('images', [])
                            images_data = [img for idx, img in enumerate(existing_images_list) 
                                         if idx not in st.session_state[delete_key]]
                            if uploaded_images:
                                for img_file in uploaded_images:
                                    img_file.seek(0)
                                    encoded = encode_image(img_file)
                                    if encoded:
                                        images_data.append(encoded)
                            if new_title != article_to_edit:
                                delete_article(st.session_state.username, article_to_edit)
                            if save_article(st.session_state.username, new_title, categories, new_content, images_data,
                                          created=current_data.get("created")):
                                st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
                                st.session_state[delete_key] = []
                                st.success(f"✅ 記事「{new_title}」を更新しました！")
                                st.rerun()
                            else:
                                st.error("記事の更新に失敗しました")
        else:
            st.info("編集する記事がありません")

    elif menu == "🗑️ 記事を削除":
        st.header("記事を削除")
        st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
        if st.session_state.encyclopedia:
            article_to_delete = st.selectbox("削除する記事を選択", sorted(st.session_state.encyclopedia.keys()))
            if article_to_delete:
                st.warning(f"本当に「{article_to_delete}」を削除しますか？")
                preview_data = st.session_state.encyclopedia[article_to_delete]
                preview_images = preview_data.get('images', [])
                if preview_images:
                    st.write(f"**この記事の画像 ({len(preview_images)}枚) も削除されます:**")
                    del_preview_cols = st.columns(min(len(preview_images), 3))
                    for idx, img_data in enumerate(preview_images):
                        img = decode_image(img_data)
                        if img:
                            with del_preview_cols[idx % 3]:
                                st.image(img, caption=f"画像 {idx + 1}", width=150)
                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("🗑️ 削除", type="primary"):
                        if delete_article(st.session_state.username, article_to_delete):
                            st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
                            st.success(f"記事「{article_to_delete}」を削除しました")
                            st.rerun()
                        else:
                            st.error("記事の削除に失敗しました")
                with col2:
                    st.empty()
        else:
            st.info("削除する記事がありません")

    elif menu == "📊 統計情報":
        st.header("統計情報")
        st.session_state.encyclopedia = get_user_encyclopedia(st.session_state.username)
        if st.session_state.encyclopedia:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📚 総記事数", len(st.session_state.encyclopedia))
            with col2:
                all_categories = set()
                for article in st.session_state.encyclopedia.values():
                    cats = article.get("category", ["未分類"])
                    if isinstance(cats, list):
                        all_categories.update(cats)
                    else:
                        all_categories.add(cats)
                st.metric("🏷️ カテゴリー数", len(all_categories))
            with col3:
                total_chars = sum(len(v.get("content", "")) for v in st.session_state.encyclopedia.values())
                st.metric("✍️ 総文字数", f"{total_chars:,}")
            with col4:
                articles_with_images = sum(1 for v in st.session_state.encyclopedia.values() if v.get("images"))
                total_images = sum(len(v.get("images", [])) for v in st.session_state.encyclopedia.values())
                st.metric("🖼️ 総画像数", total_images)
                st.caption(f"画像付き記事: {articles_with_images}件")
            st.markdown("---")
            st.subheader("カテゴリー別記事数")
            category_count = {}
            for article in st.session_state.encyclopedia.values():
                cats = article.get("category", ["未分類"])
                if isinstance(cats, list):
                    for cat in cats:
                        category_count[cat] = category_count.get(cat, 0) + 1
                else:
                    category_count[cats] = category_count.get(cats, 0) + 1
            for cat, count in sorted(category_count.items(), key=lambda x: x[1], reverse=True):
                st.write(f"**{cat}**: {count}件")
        else:
            st.info("まだ記事がありません")

    st.markdown("---")
    st.markdown("💡 **ヒント**: マーカーを使うには `<yellow>文字</yellow>` のように囲んでください！")