import streamlit as st
from openai import OpenAI

1. 画面の基本設定
st.set_page_config(page_title="ナラティブ・ポリシー・アドバイザー", layout="centered")
st.title("📖 ナラティブ・ポリシー・アドバイザー")
st.caption("統計データの背景にある「一人ひとりの物語」を可視化するプロトタイプ")

2. サイドバーでの属性選択
st.sidebar.header("対象者の属性を選択")
age = st.sidebar.selectbox("年代", ["40代前半", "40代後半", "50代前半"])
employment = st.sidebar.selectbox("雇用形態", ["不本意非正規（事務アシスタント等）", "無業者", "その他"])
family = st.sidebar.selectbox("家族構成", ["単身", "夫婦と子", "ひとり親", "親と同居（介護等）"])

3. OpenAIクライアントの初期化
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

4. 物語生成のロジック
def generate_story():
response = client.chat.completions.create(
model="gpt-4o",
messages=[
{
"role": "system",
"content": "あなたは熟練の政策アドバイザーです。ユーザーが選択した属性に基づき、統計データには現れにくい切実な300文字程度の物語を生成してください。"
},
{
"role": "user",
"content": f"属性情報：年代={age}、雇用形態={employment}、家族構成={family}"
}
],
max_tokens=600,
temperature=0.7
)
return response.choices[0].message.content

5. 生成ボタンと結果表示
if st.sidebar.button("ナラティブ（物語）を生成"):
with st.spinner('AIが物語を執筆中...'):
try:
story_text = generate_story()
st.subheader("生成されたナラティブ")
st.write(story_text)
st.divider()
st.info("💡 この物語の背景：就職氷河期世代の不本意非正規労働者は約35万人にのぼります。")
st.markdown("参照：")
except Exception as e:
st.error(f"エラーが発生しました: {e}")
