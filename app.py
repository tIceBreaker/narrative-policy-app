import streamlit as st
from openai import OpenAI

# =========================
# OpenAI Client Setup
# =========================
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# =========================
# UI 設定
# =========================
st.set_page_config(page_title="ナラティブ・ポリシー・アドバイザー", layout="wide")

st.title("📘 ナラティブ・ポリシー・アドバイザー")

# -------------------------
# サイドバー：属性入力
# -------------------------
st.sidebar.header("属性を選択")

年代 = st.sidebar.selectbox(
    "年代",
    ["30代前半", "30代後半", "40代前半", "40代後半"]
)

雇用形態 = st.sidebar.selectbox(
    "雇用形態",
    ["正規", "非正規", "フリーランス", "求職中"]
)

家族構成 = st.sidebar.selectbox(
    "家族構成",
    ["単身", "夫婦のみ", "夫婦＋子ども", "ひとり親"]
)

# -------------------------
# 参照データ（簡易実装）
# 属性に応じてリンク/データをマッピング
# -------------------------
reference_data = {
    "単身": {
        "label": "東京都の単身世帯率（オープンデータ）",
        "url": "https://www.opendata.metro.tokyo.lg.jp/"
    },
    "非正規": {
        "label": "不本意非正規労働者数（総務省統計局）",
        "url": "https://www.stat.go.jp/"
    },
    "求職中": {
        "label": "有効求人倍率（ハローワーク 東京）",
        "url": "https://www.hellowork.mhlw.go.jp/"
    },
    "夫婦＋子ども": {
        "label": "東京都子育て支援関連データ",
        "url": "https://www.kosodate.metro.tokyo.lg.jp/"
    }
}

# 選択属性に合うデータを抽出（複数条件に対応）
selected_references = []
for key, data in reference_data.items():
    if key in 家族構成 or key in 雇用形態:
        selected_references.append(data)

if not selected_references:  # fallback
    selected_references.append({
        "label": "東京都オープンデータカタログ",
        "url": "https://www.opendata.metro.tokyo.lg.jp/"
    })

# -------------------------
# GPT 物語生成
# -------------------------

system_prompt = """
あなたは熟練のナラティブ・ポリシー・アドバイザーです。
選択された属性（年代・雇用・家族）に基づき、以下の3点を意識して300字程度の物語を書いてください。

① 平均値では見えない『生活のディテール（例：電卓を叩く音、子供の送迎の焦り）』。
② ポテンシャルを発揮するための『条件整理（アクセス設計）』の欠如。
③ 特定のオープンデータ（例：不本意非正規労働者数35万人）を感じさせるリアリティ。
"""

def generate_story():
    user_prompt = f"""
    属性は以下です。
    ・年代：{年代}
    ・雇用形態：{雇用形態}
    ・家族構成：{家族構成}

    上記の設定で物語を書いてください。
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=500
    )

    return response.choices[0].message["content"]

# -------------------------
# UI：物語生成ボタン
# -------------------------
generate_button = st.button("📝 物語を生成")

if generate_button:
    with st.spinner("物語を生成しています…"):
        story = generate_story()
        st.subheader("📖 生成された物語")
        st.write(story)

        # 根拠データ表示
        st.subheader("🔍 参照したオープンデータ")
        for ref in selected_references:
            st.markdown(f"- {ref['url']}")

else:
    st.info("左のメニューで属性を選び、「物語を生成」ボタンを押してください。")
