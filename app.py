import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI

# =========================
# 基本設定
# =========================
st.set_page_config(page_title="ナラティブ・ポリシー・アドバイザー", layout="wide")
st.title("📖 ナラティブ・ポリシー・アドバイザー")
st.caption("東京都オープンデータを根拠として、対象者像・物語・ニーズ・政策仮説を生成します。")

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

CURRENT_YEAR = datetime.now().year

# =========================
# ユーティリティ
# =========================
def safe_json_load(text: str) -> dict:
    """LLMの返答からJSONを安全に抽出"""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("JSONの解析に失敗しました。")

def birth_cohort_label(start_year: int, end_year: int) -> str:
    mid_age_from = CURRENT_YEAR - end_year
    mid_age_to = CURRENT_YEAR - start_year
    return f"{start_year}〜{end_year}年生（{mid_age_from}〜{mid_age_to}歳相当）"

def derived_age_category(start_year: int, end_year: int) -> str:
    """
    表示用カテゴリ。
    5年刻みの生年を元に、物語説明上のカテゴリも付ける。
    """
    age_from = CURRENT_YEAR - end_year
    age_to = CURRENT_YEAR - start_year
    mid = (age_from + age_to) / 2

    if 40 <= mid < 45:
        return "40代前半"
    elif 45 <= mid < 50:
        return "40代後半"
    elif 50 <= mid < 55:
        return "50代前半"
    else:
        return "就職氷河期世代"

def to_official_age_band(start_year: int, end_year: int) -> str:
    """
    東京都労働力統計の10歳階級に寄せるための近似。
    """
    age_from = CURRENT_YEAR - end_year
    age_to = CURRENT_YEAR - start_year
    mid = (age_from + age_to) / 2

    if mid < 45:
        return "35～44歳"
    elif mid < 55:
        return "45～54歳"
    else:
        return "55～64歳"

def first_text_column(df: pd.DataFrame) -> str:
    for c in df.columns:
        if df[c].dtype == object:
            return c
    return df.columns[0]

def normalize_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].astype(str).str.replace(",", "", regex=False)
            out[c] = pd.to_numeric(out[c], errors="ignore")
    return out

def load_csv_flexible(url: str) -> pd.DataFrame:
    """
    東京都のCSVは文字コードや構造が揺れるため、複数パターンで読む。
    """
    r = requests.get(url, timeout=20)
    r.raise_for_status()

    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(pd.io.common.BytesIO(r.content), encoding=enc)
        except Exception as e:
            last_err = e

    raise last_err

# =========================
# 東京都オープンデータ カタログ / API
# =========================
CKAN_API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search"

@st.cache_data(ttl=60 * 60 * 12)
def search_tokyo_catalog(query: str, rows: int = 10):
    params = {"q": query, "rows": rows}
    r = requests.get(CKAN_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        return []
    return data["result"]["results"]

@st.cache_data(ttl=60 * 60 * 12)
def get_dataset_resources_by_title_keyword(title_keyword: str):
    """
    タイトルにキーワードを含むデータセットを検索し、最初の候補を返す
    """
    results = search_tokyo_catalog(title_keyword, rows=10)
    for ds in results:
        if title_keyword.replace(" ", "")[:4] in ds.get("title", "").replace(" ", ""):
            return ds
    return results[0] if results else None

def get_resource_url(dataset: dict, resource_name_keyword: str):
    if not dataset:
        return None
    for res in dataset.get("resources", []):
        name = (res.get("name") or "")
        if resource_name_keyword in name:
            return res.get("url"), name
    return None, None

# =========================
# 参照する東京都オープンデータ
# =========================
def build_reference_catalog():
    return [
        {
            "name": "東京の労働力 統計データ（令和4年平均）",
            "url": "https://catalog.data.metro.tokyo.lg.jp/ja/dataset/t000003d0000000591",
            "data_tags": ["人口分布", "就業状態", "年齢階級", "雇用形態"],
            "issue_tags": ["就労", "無業", "非正規", "再就職"],
            "why": "年代別の就業状態、雇用形態、完全失業などの把握に利用"
        },
        {
            "name": "東京の労働力 統計データ（令和3年平均）",
            "url": "https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000400",
            "data_tags": ["人口分布", "就業状態", "男女別", "雇用形態"],
            "issue_tags": ["就労", "失業", "非正規", "労働市場"],
            "why": "男女別・年齢階級別の就業状態の補助参照"
        },
        {
            "name": "東京都世帯数の予測 第5-1表 区市町村別ひとり親と子供の世帯数",
            "url": "https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000035",
            "data_tags": ["世帯構成", "ひとり親", "地域別"],
            "issue_tags": ["子育て", "世帯支援", "家計", "住居"],
            "why": "家族構成、とくにひとり親に関する政策文脈の参照"
        },
        {
            "name": "【行政資料集】子育て（ひとり親家庭等医療費助成制度受給世帯数を含む）",
            "url": "https://catalog.data.metro.tokyo.lg.jp/dataset/t131032d0000000039",
            "data_tags": ["ひとり親", "受給世帯数", "子育て支援"],
            "issue_tags": ["福祉", "家計", "医療費", "養育"],
            "why": "ひとり親関連の支援規模感の補助参照"
        },
        {
            "name": "東京都男女年齢（5歳階級）別人口の予測",
            "url": "https://www.toukei.metro.tokyo.lg.jp/dyosoku/dy-index.htm",
            "data_tags": ["人口", "男女別", "5歳階級", "将来推計"],
            "issue_tags": ["人口構成", "対象母数"],
            "why": "生年5年区分に近い人口構成を説明する基礎参照"
        },
    ]

# =========================
# 人口分布・規模感の簡易推計
# =========================
@st.cache_data(ttl=60 * 60 * 12)
def get_labor_force_dataset():
    """
    令和4年平均を優先し、なければ令和3年平均を返す
    """
    ds = get_dataset_resources_by_title_keyword("東京の労働力 統計データ（令和4年平均）")
    if ds:
        return ds
    return get_dataset_resources_by_title_keyword("東京の労働力 統計データ（令和3年平均）")

def detect_age_column(df: pd.DataFrame, official_age_band: str):
    """
    例: 実数／45～54歳（千人、％）
    """
    candidates = []
    for c in df.columns:
        s = str(c)
        if official_age_band in s and "実数" in s:
            candidates.append(c)

    # 雇用形態別表などは別表記の可能性もある
    if not candidates:
        for c in df.columns:
            if official_age_band in str(c):
                candidates.append(c)

    return candidates[0] if candidates else None

def detect_row(df: pd.DataFrame, keywords):
    text_col = first_text_column(df)
    mask = df[text_col].astype(str)
    for kw in keywords:
        hit = df[mask.str.contains(kw, na=False)]
        if not hit.empty:
            return hit.iloc[0]
    return None

def format_thousand_persons(value):
    try:
        v = float(value)
        return f"{v:.1f}千人"
    except Exception:
        return "不明"

def estimate_scale(selected_gender: str, birth_start: int, birth_end: int, emp: str):
    """
    東京都の労働力統計から、年齢階級近似ベースの規模感を出す。
    厳密な対象者数ではなく、政策検討上の参考規模。
    """
    ds = get_labor_force_dataset()
    if not ds:
        return {"summary": "東京都オープンデータから規模感を取得できませんでした。", "details": [], "source_links": []}

    official_age_band = to_official_age_band(birth_start, birth_end)

    # 男女別の第3表候補
    if selected_gender == "男性":
        age_table_kw = "第３表 年齢階級別就業状態（男）"
    elif selected_gender == "女性":
        age_table_kw = "第３表 年齢階級別就業状態（女）"
    else:
        age_table_kw = "第３表 年齢階級別就業状態（男女計）"

    age_url, age_name = get_resource_url(ds, age_table_kw)
    emp_url, emp_name = get_resource_url(ds, "第８表 年齢階級、雇用形態別の役員を除く雇用者数")

    details = []
    source_links = []

    try:
        if age_url:
            df_age = normalize_numeric_columns(load_csv_flexible(age_url))
            age_col = detect_age_column(df_age, official_age_band)
            if age_col:
                employed = detect_row(df_age, ["就業者", "有業者"])
                unemployed = detect_row(df_age, ["完全失業者", "失業者"])
                labor_force = detect_row(df_age, ["労働力人口"])

                if labor_force is not None:
                    details.append({
                        "label": f"{official_age_band}の労働力人口",
                        "value": format_thousand_persons(labor_force.get(age_col))
                    })
                if employed is not None:
                    details.append({
                        "label": f"{official_age_band}の就業者",
                        "value": format_thousand_persons(employed.get(age_col))
                    })
                if unemployed is not None:
                    details.append({
                        "label": f"{official_age_band}の完全失業者",
                        "value": format_thousand_persons(unemployed.get(age_col))
                    })

            source_links.append({"name": age_name or "年齢階級別就業状態", "url": age_url})
    except Exception:
        pass

    try:
        if emp_url and emp in ["正規", "非正規"]:
            df_emp = normalize_numeric_columns(load_csv_flexible(emp_url))
            age_col = detect_age_column(df_emp, official_age_band)
            if age_col:
                if emp == "正規":
                    row = detect_row(df_emp, ["正規", "正規の職員", "正社員"])
                else:
                    row = detect_row(df_emp, ["非正規", "パート", "アルバイト", "契約社員", "派遣"])

                if row is not None:
                    details.append({
                        "label": f"{official_age_band}の{emp}雇用者",
                        "value": format_thousand_persons(row.get(age_col))
                    })

            source_links.append({"name": emp_name or "雇用形態別雇用者数", "url": emp_url})
    except Exception:
        pass

    if emp == "無業者":
        details.append({
            "label": "補足",
            "value": "無業者は『就業者ではない層』として、年齢階級別就業状態の完全失業者・非労働力人口を参考に解釈してください。"
        })
    elif emp == "休職中":
        details.append({
            "label": "補足",
            "value": "休職中の直接統計は乏しいため、就業者数・雇用形態・療養/介護等の制約情報と併せて解釈します。"
        })

    summary = f"東京都の公式オープンデータをもとに、{official_age_band}の近似階級で規模感を表示しています。生年5年区分と統計表の年齢階級が一致しないため、政策検討用の参考値です。"

    return {"summary": summary, "details": details, "source_links": source_links}

# =========================
# 物語生成
# =========================
def build_prompt(user_context, references):
    return f"""
あなたは東京都の就職氷河期世代支援を担当する政策アドバイザーです。
以下の属性と前提条件、および東京都オープンデータの参照情報を踏まえて、
JSONのみで出力してください。

【対象者属性】
- 性別: {user_context['gender']}
- 生年区分: {user_context['birth_label']}
- 年代カテゴリ: {user_context['age_category']}
- 雇用形態: {user_context['employment']}
- 家族構成: {user_context['family']}
- 最終学歴: {user_context['education']}
- 健康/就労制約: {user_context['health_constraint']}
- ケア責任: {user_context['care_responsibility']}
- 住居状況: {user_context['housing']}
- デジタル利用環境: {user_context['digital_access']}
- 相談先の有無: {user_context['support_network']}

【追加の検討条件】
- 支援方法: {", ".join(user_context['support_methods']) if user_context['support_methods'] else "指定なし"}
- 支援期間: {user_context['support_period']}
- 政策目標: {user_context['policy_goal']}
- 当事者の制約: {", ".join(user_context['constraints']) if user_context['constraints'] else "指定なし"}

【東京都オープンデータ参照情報】
{json.dumps(references, ensure_ascii=False, indent=2)}

【出力条件】
1. story: 300〜450文字程度の具体的な主人公の物語
2. needs: 主人公の主要ニーズを3〜5個
3. policy_hypotheses: 政策仮説を3〜5個
4. issue_tags: 3〜7個
5. data_tags: 3〜7個
6. evidence_comment: 参照データをどう読んだかを120文字程度で簡潔に
7. cautions: 推計や解釈上の注意点を2個以内

JSONスキーマ:
{{
  "story": "...",
  "needs": ["...", "..."],
  "policy_hypotheses": ["...", "..."],
  "issue_tags": ["...", "..."],
  "data_tags": ["...", "..."],
  "evidence_comment": "...",
  "cautions": ["...", "..."]
}}
""".strip()

def generate_story_and_hypotheses(user_context, references):
    prompt = build_prompt(user_context, references)
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": "あなたは政策設計、福祉、就労支援、データ解釈に強いアシスタントです。必ずJSONのみを返してください。"
            },
            {"role": "user", "content": prompt}
        ]
    )
    return safe_json_load(response.choices[0].message.content)

# =========================
# UI: サイドバー
# =========================
st.sidebar.header("対象者の属性を選択")

gender = st.sidebar.selectbox("① 性別", ["回答しない", "女性", "男性"])

birth_options = {
    birth_cohort_label(1980, 1984): (1980, 1984),  # 40代前半相当
    birth_cohort_label(1975, 1979): (1975, 1979),  # 40代後半相当
    birth_cohort_label(1970, 1974): (1970, 1974),  # 50代前半相当
}
birth_selected_label = st.sidebar.selectbox("② 生年（5年区分）", list(birth_options.keys()))
birth_start, birth_end = birth_options[birth_selected_label]
age_category = derived_age_category(birth_start, birth_end)

employment = st.sidebar.selectbox("③ 雇用形態", ["正規", "非正規", "無業者", "休職中"])
family = st.sidebar.selectbox("④ 家族構成", ["単身", "夫婦のみ", "夫婦と子", "ひとり親", "親と同居"])

st.sidebar.markdown("---")
st.sidebar.subheader("⑤ 支援検討で把握したい追加属性")

education = st.sidebar.selectbox(
    "最終学歴",
    ["指定なし", "中学・高校", "専門学校", "短大・高専", "大学", "大学院"]
)

health_constraint = st.sidebar.selectbox(
    "健康/就労制約",
    ["指定なし", "特になし", "メンタル不調", "身体疾患", "障害がある", "通院中", "療養中"]
)

care_responsibility = st.sidebar.selectbox(
    "ケア責任",
    ["指定なし", "なし", "子育てあり", "介護あり", "子育てと介護の両方"]
)

housing = st.sidebar.selectbox(
    "住居状況",
    ["指定なし", "持ち家", "民間賃貸", "公営住宅", "親族宅同居", "住居不安定"]
)

digital_access = st.sidebar.selectbox(
    "デジタル利用環境",
    ["指定なし", "スマホ中心", "PCあり", "ネット利用に不安", "ほとんど使わない"]
)

support_network = st.sidebar.selectbox(
    "相談先の有無",
    ["指定なし", "家族に相談できる", "友人に相談できる", "公的支援につながっている", "相談先がほぼない"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("前提条件を追加")

support_methods = st.sidebar.multiselect(
    "検討したい支援方法",
    ["就労支援", "職業訓練", "療養支援", "リハビリ", "生活再建支援", "住居支援", "家計支援", "心理的支援", "伴走支援"]
)

support_period = st.sidebar.selectbox(
    "支援期間",
    ["短期（〜3か月）", "中期（3〜12か月）", "中長期（1〜3年）", "長期（3年以上）"]
)

policy_goal = st.sidebar.selectbox(
    "政策目標",
    ["再就職", "就業継続", "所得向上", "生活安定", "孤立防止", "医療・福祉との接続", "自己効力感の回復"]
)

constraints = st.sidebar.multiselect(
    "当事者の制約",
    ["体調不安", "育児負担", "介護負担", "ブランク長期化", "学び直し負担", "通勤困難", "対人不安", "家計逼迫", "デジタル弱者"]
)

# =========================
# メイン表示
# =========================
st.subheader("現在の設定")
col1, col2 = st.columns(2)

with col1:
    st.write(f"**性別**: {gender}")
    st.write(f"**生年区分**: {birth_selected_label}")
    st.write(f"**年代カテゴリ**: {age_category}")
    st.write(f"**雇用形態**: {employment}")
    st.write(f"**家族構成**: {family}")

with col2:
    st.write(f"**最終学歴**: {education}")
    st.write(f"**健康/就労制約**: {health_constraint}")
    st.write(f"**ケア責任**: {care_responsibility}")
    st.write(f"**住居状況**: {housing}")
    st.write(f"**デジタル利用環境**: {digital_access}")
    st.write(f"**相談先**: {support_network}")

st.markdown("---")

if st.button("物語を生成"):
    with st.spinner("東京都オープンデータを参照しながら生成中..."):
        try:
            references = build_reference_catalog()

            user_context = {
                "gender": gender,
                "birth_label": birth_selected_label,
                "age_category": age_category,
                "employment": employment,
                "family": family,
                "education": education,
                "health_constraint": health_constraint,
                "care_responsibility": care_responsibility,
                "housing": housing,
                "digital_access": digital_access,
                "support_network": support_network,
                "support_methods": support_methods,
                "support_period": support_period,
                "policy_goal": policy_goal,
                "constraints": constraints,
            }

            result = generate_story_and_hypotheses(user_context, references)
            scale = estimate_scale(gender, birth_start, birth_end, employment)

            st.subheader("生成された物語")
            st.write(result.get("story", ""))

            c1, c2 = st.columns(2)

            with c1:
                st.markdown("### 主人公のニーズ")
                for n in result.get("needs", []):
                    st.markdown(f"- {n}")

                st.markdown("### 課題タグ")
                issue_tags = result.get("issue_tags", [])
                if issue_tags:
                    st.caption(" / ".join([f"#{t}" for t in issue_tags]))

            with c2:
                st.markdown("### 政策仮説")
                for h in result.get("policy_hypotheses", []):
                    st.markdown(f"- {h}")

                st.markdown("### データタグ")
                data_tags = result.get("data_tags", [])
                if data_tags:
                    st.caption(" / ".join([f"#{t}" for t in data_tags]))

            st.markdown("---")
            st.markdown("### 人口分布・該当当事者の規模感（簡易推計）")
            st.info(scale.get("summary", ""))

            if scale.get("details"):
                for d in scale["details"]:
                    st.markdown(f"- **{d['label']}**: {d['value']}")
            else:
                st.write("該当する規模感を自動推計できませんでした。参照リンクをご確認ください。")

            st.markdown("---")
            st.markdown("### 根拠データの読み方")
            st.write(result.get("evidence_comment", ""))

            cautions = result.get("cautions", [])
            if cautions:
                st.markdown("### 解釈上の注意")
                for c in cautions:
                    st.markdown(f"- {c}")

            st.markdown("---")
            st.markdown("### 参照した東京都オープンデータ")
            for ref in references:
                st.markdown(f"**[{ref['name']}]({ref['url']})**")
                st.write(ref["why"])
                st.caption(
                    "データタグ: "
                    + " / ".join([f"#{x}" for x in ref["data_tags"]])
                    + "　　課題タグ: "
                    + " / ".join([f"#{x}" for x in ref["issue_tags"]])
                )

            if scale.get("source_links"):
                st.markdown("### 規模感推計に使用したCSVリソース")
                for src in scale["source_links"]:
                    st.markdown(f"- [{src['name']}]({src['url']})")

        except Exception as e:
            st.error(f"エラー: {e}")
