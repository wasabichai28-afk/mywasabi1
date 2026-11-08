import csv
import re
import unicodedata
from datetime import date
from pathlib import Path

import streamlit as st


DATA_DIRECTORY = Path(__file__).parent


def resolve_data_file(filename: str) -> Path:
    path = DATA_DIRECTORY / filename
    if path.is_file():
        return path

    stem = Path(filename).stem
    matching_files = sorted(DATA_DIRECTORY.glob(f"{stem}*.csv"))
    exact_match = next((match for match in matching_files if match.name == filename), None)
    if exact_match is not None:
        return exact_match
    if matching_files:
        return matching_files[0]
    return path


DATA_PATH = resolve_data_file("総データ - oll.csv")
WELLNESS_LIST_PATH = resolve_data_file("プチ養生 - プチ養生一覧.csv")
SYMPTOM_ADVICE_PATH = resolve_data_file("プチ養生 - 症状別おすすめ養生.csv")
RECIPE_PATH = resolve_data_file("プチ養生 - レシピ.csv")
PAGE_SIZE = 12
RESULT_COLUMNS = 6
WELLNESS_PAGE = st.query_params.get("page") == "wellness"
RECIPE_PAGE = st.query_params.get("page") == "recipe"
SEARCH_FIELDS = (
    "食材名",
    "検索用キーワード",
)
DISPLAY_FIELDS = (
    "食材名",
    "分類",
    "五性",
    "五味",
    "帰経",
    "一般的な効能",
    "薬膳効能・作用",
    "おすすめの症状・不調",
    "おすすめの組み合わせ・スパイス",
    "備考・料理例",
    "注意点・摂取のコツ",
    "避けたほうがよい体質・証",
)


@st.cache_data
def load_ingredients() -> list[dict[str, str]]:
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"食材データが見つかりません: {DATA_PATH.name}")

    with DATA_PATH.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_fields = set(DISPLAY_FIELDS + SEARCH_FIELDS + ("食材ID",))
        if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
            raise ValueError("CSVの列名が想定と異なります。食材データの形式を確認してください。")
        ingredients = [dict(row) for row in reader]

    if not ingredients:
        raise ValueError(f"{DATA_PATH.name} に食材データがありません。")

    ingredient_ids = [
        (ingredient.get("食材ID") or "").strip() for ingredient in ingredients
    ]
    if any(not ingredient_id for ingredient_id in ingredient_ids):
        raise ValueError("食材IDが空のレコードがあります。CSVを確認してください。")

    for row_number, ingredient in enumerate(ingredients, start=2):
        if None in ingredient or any(
            not (ingredient.get(field) or "").strip()
            for field in required_fields
            if field != "食材ID"
        ):
            raise ValueError(
                f"{DATA_PATH.name} の{row_number}行目に空欄または列数の不整合があります。"
            )

    if len(set(ingredient_ids)) != len(ingredient_ids):
        raise ValueError("食材IDが重複しています。CSV内の食材IDを一意にしてください。")

    return ingredients


@st.cache_data
def load_wellness_data(
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    datasets = (
        (
            WELLNESS_LIST_PATH,
            ("ID", "タイトル", "分類", "対象季節", "対象の悩み・体質",
             "アドバイス本文", "おすすめの食材", "ポイント・コツ"),
        ),
        (
            SYMPTOM_ADVICE_PATH,
            ("症状ID", "症状名", "主な原因・タイプ（東洋医学）",
             "おすすめの食材・生薬", "養生法・アドバイス", "避けたいこと"),
        ),
    )
    loaded_datasets = []
    for path, required_fields in datasets:
        if not path.is_file():
            raise FileNotFoundError(f"養生データが見つかりません: {path.name}")

        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or not set(required_fields).issubset(reader.fieldnames):
                raise ValueError(f"{path.name} の列名が想定と異なります。")
            rows = list(reader)

        id_field = required_fields[0]
        identifiers = []
        for row_number, row in enumerate(rows, start=2):
            if None in row or any(not (row.get(field) or "").strip() for field in required_fields):
                raise ValueError(f"{path.name} の{row_number}行目に空欄または列数の不整合があります。")
            identifiers.append(row[id_field].strip())
        if not rows:
            raise ValueError(f"{path.name} にデータがありません。")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{path.name} でIDが重複しています。")

        loaded_datasets.append(rows)

    return loaded_datasets[0], loaded_datasets[1]


@st.cache_data
def load_recipe_data() -> list[dict[str, str]]:
    if not RECIPE_PATH.is_file():
        raise FileNotFoundError(f"レシピデータが見つかりません: {RECIPE_PATH.name}")

    with RECIPE_PATH.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_fields = (
            "レシピ名",
            "分類",
            "主な効能",
            "材料",
            "作り方",
            "ポイント",
            "この症状で悩んでいる人におすすめ！",
        )
        if not reader.fieldnames or not set(required_fields).issubset(reader.fieldnames):
            raise ValueError(f"{RECIPE_PATH.name} の列名が想定と異なります。")
        recipes = [dict(row) for row in reader]

    if not recipes:
        raise ValueError(f"{RECIPE_PATH.name} にレシピデータがありません。")

    for row_number, row in enumerate(recipes, start=2):
        if None in row or any(not (row.get(field) or "").strip() for field in required_fields):
            raise ValueError(f"{RECIPE_PATH.name} の{row_number}行目に空欄があります。")

    return recipes


def normalize_symptom_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s・,，、/／()（）]+", "", normalized)


def symptom_match_terms(value: str) -> set[str]:
    return {
        normalize_symptom_text(term)
        for term in re.split(r"[\s・,，、/／()（）]+", value)
        if term
    }


def find_related_recipes(
    symptom_name: str,
    recipes: list[dict[str, str]],
    limit: int = 3,
) -> list[dict[str, str]]:
    symptom_core = re.split(r"[（(]", symptom_name, maxsplit=1)[0]
    symptom_terms = symptom_match_terms(symptom_core)
    if not symptom_terms:
        return []

    matches: list[dict[str, str]] = []
    for recipe in recipes:
        symptom_text = recipe.get("この症状で悩んでいる人におすすめ！", "")
        candidate_values = [
            value.strip()
            for value in re.split(r"[、,，]", symptom_text)
            if value.strip()
        ]
        for candidate in candidate_values:
            if symptom_terms.intersection(symptom_match_terms(candidate)):
                matches.append(recipe)
                break

    unique_matches = []
    seen: set[str] = set()
    for recipe in matches:
        recipe_name = recipe.get("レシピ名", "")
        if recipe_name and recipe_name not in seen:
            seen.add(recipe_name)
            unique_matches.append(recipe)
        if len(unique_matches) >= limit:
            break
    return unique_matches


def matches_query(ingredient: dict[str, str], query: str) -> bool:
    terms = [
        term
        for term in re.split(r"[\s、，,]+", query.casefold())
        if term
    ]
    if not terms:
        return True

    searchable_text = " ".join(ingredient.get(field, "") for field in SEARCH_FIELDS).casefold()
    return all(term in searchable_text for term in terms)


def find_recommended_ingredient(
    recommendation: str, ingredients: list[dict[str, str]]
) -> dict[str, str] | None:
    ingredient_aliases = {
        "棗": ("なつめ", "ナツメ", "大棗"),
        "タマネギ": ("玉ねぎ", "玉葱"),
        "シソ": ("紫蘇", "大葉"),
        "ユリ根": ("ゆり根", "百合根", "百合"),
        "カボチャ": ("かぼちゃ", "南瓜"),
        "サツマイモ": ("さつまいも", "薩摩芋", "甘薯"),
        "キュウリ": ("きゅうり", "胡瓜"),
        "カブ": ("かぶ", "蕪"),
        "青魚（サバ・サンマ）": ("サバ",),
    }

    def normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return "".join(
            chr(ord(character) - 0x60)
            if "\u30a1" <= character <= "\u30f6"
            else character
            for character in normalized
            if not character.isspace() and character not in "・,，、/／()（）"
        )

    normalized_recommendation = normalize(recommendation)
    normalized_aliases = {
        normalize(alias)
        for alias in ingredient_aliases.get(recommendation.strip(), ())
    }
    recommendation_terms = {normalized_recommendation, *normalized_aliases}
    exact_name_matches = []
    keyword_matches = []

    for ingredient in ingredients:
        name = ingredient.get("食材名", "").strip()
        primary_name = re.split(r"[（(]", name, maxsplit=1)[0].strip()
        normalized_name = normalize(name)
        normalized_primary_name = normalize(primary_name)
        if recommendation_terms.intersection((normalized_name, normalized_primary_name)):
            exact_name_matches.append(ingredient)
            continue

        searchable_terms = re.split(
            r"[\s・,，、/／()（）]+",
            " ".join((name, ingredient.get("検索用キーワード", ""))),
        )
        if any(
            normalize(term) in recommendation_terms
            for term in searchable_terms
            if term
        ):
            keyword_matches.append(ingredient)

    if exact_name_matches:
        return exact_name_matches[0]
    return keyword_matches[0] if keyword_matches else None


def clear_search() -> None:
    st.session_state["query_input"] = ""
    st.session_state["result_category_input"] = "すべて"
    st.session_state["submitted_query"] = ""
    st.session_state["search_submitted"] = False
    st.session_state["search_results_open"] = False
    st.session_state["result_page"] = 1
    st.session_state["selected_ingredient_id"] = ""


def reset_results_for_category() -> None:
    st.session_state["result_page"] = 1
    st.session_state["selected_ingredient_id"] = ""


def change_page(step: int) -> None:
    page_count = st.session_state.get("result_page_count", 1)
    current_page = st.session_state.get("result_page", 1)
    st.session_state["result_page"] = min(max(current_page + step, 1), page_count)
    st.session_state["selected_ingredient_id"] = ""


def select_ingredient(ingredient_id: str) -> None:
    st.session_state["selected_ingredient_id"] = ingredient_id


def clear_selected_ingredient() -> None:
    st.session_state["selected_ingredient_id"] = ""


def close_search_results_dialog() -> None:
    st.session_state["search_results_open"] = False


def show_ingredient_details(ingredient: dict[str, str]) -> None:
    st.markdown(f"### {ingredient['食材名']}")
    st.write(ingredient["一般的な効能"])
    st.caption(
        f"五性：{ingredient['五性']}　｜　五味：{ingredient['五味']}　｜　帰経：{ingredient['帰経']}"
    )

    for label, key in (
        ("薬膳のはたらき", "薬膳効能・作用"),
        ("おすすめの体調", "おすすめの症状・不調"),
        ("相性のよい組み合わせ", "おすすめの組み合わせ・スパイス"),
        ("料理例", "備考・料理例"),
    ):
        value = ingredient.get(key, "").strip()
        if value:
            st.markdown(f"**{label}**")
            st.write(value)

    for label, key in (
        ("気をつけたいこと", "注意点・摂取のコツ"),
        ("控えめにしたい体質", "避けたほうがよい体質・証"),
    ):
        value = ingredient.get(key, "").strip()
        if value:
            st.warning(f"**{label}**\n\n{value}")


@st.dialog("食材の詳細")
def show_ingredient_dialog(ingredient: dict[str, str]) -> None:
    show_ingredient_details(ingredient)


@st.dialog(
    "食材の検索結果",
    width="large",
    on_dismiss=close_search_results_dialog,
)
def show_search_results_dialog(
    ingredients: list[dict[str, str]],
    query: str,
    categories: list[str],
) -> None:
    st.markdown(f"**検索した食材：** {query.strip() or 'すべて'}")
    selected_category = st.selectbox(
        "分類で絞り込む",
        ["すべて", *categories],
        key="result_category_input",
        on_change=reset_results_for_category,
    )
    filtered = [
        item for item in ingredients
        if matches_query(item, query)
        and (
            selected_category == "すべて"
            or item["分類"] == selected_category
        )
    ]
    st.write(f"該当する食材：**{len(filtered)}件**")

    selected_ingredient_id = st.session_state.get("selected_ingredient_id", "")
    detail = (
        filtered[0]
        if len(filtered) == 1
        else next(
            (item for item in filtered if item["食材ID"] == selected_ingredient_id),
            None,
        )
    )
    if detail:
        if len(filtered) > 1:
            st.button(
                "検索結果に戻る",
                key="back-to-search-results",
                on_click=clear_selected_ingredient,
            )
        show_ingredient_details(detail)
    elif not filtered:
        st.info("該当する食材が見つかりませんでした。別の食材名で検索してください。")
    else:
        page_count = (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE
        st.session_state["result_page_count"] = page_count
        page = min(st.session_state.get("result_page", 1), page_count)
        st.session_state["result_page"] = page
        start = (page - 1) * PAGE_SIZE
        page_ingredients = filtered[start : start + PAGE_SIZE]
        with st.container(key="ingredient-results"):
            for row_start in range(0, len(page_ingredients), RESULT_COLUMNS):
                columns = st.columns(RESULT_COLUMNS)
                for column, ingredient in zip(
                    columns, page_ingredients[row_start : row_start + RESULT_COLUMNS]
                ):
                    with column:
                        st.button(
                            ingredient["食材名"],
                            key=f"ingredient-{ingredient['食材ID']}",
                            type="secondary",
                            on_click=select_ingredient,
                            args=(ingredient["食材ID"],),
                            help="クリックして食材の詳細を表示",
                        )

        if page_count > 1:
            previous_col, page_col, next_col = st.columns([1, 2, 1])
            with previous_col:
                st.button(
                    "前へ",
                    key="previous-page",
                    disabled=page == 1,
                    on_click=change_page,
                    args=(-1,),
                    use_container_width=True,
                )
            with page_col:
                st.markdown(
                    f"<div style='text-align:center;padding:.5rem'>"
                    f"{page} / {page_count} ページ</div>",
                    unsafe_allow_html=True,
                )
            with next_col:
                st.button(
                    "次へ",
                    key="next-page",
                    disabled=page == page_count,
                    on_click=change_page,
                    args=(1,),
                    type="primary",
                    use_container_width=True,
                )

    st.divider()
    st.caption(
        "掲載内容は伝統的な薬膳の考え方に基づく食材選びの参考情報で、"
        "病気の診断・治療を目的としたものではありません。治療中の方、妊娠中の方、"
        "アレルギーや持病のある方は、医師・薬剤師などの専門家にご相談ください。"
    )


st.set_page_config(
    page_title="わさびの薬膳辞書",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
    :root {
        --wasabi-ink: #263a2d;
        --wasabi-green: #42634a;
        --wasabi-leaf: #73885b;
        --wasabi-paper: #f7f6ef;
        --wasabi-line: #e4e6d9;
    }
    .stApp {
        background:
            radial-gradient(ellipse at 92% 2%, rgba(216, 225, 198, .32), transparent 28rem),
            var(--wasabi-paper);
        color: var(--wasabi-ink);
        --text-color: var(--wasabi-ink);
    }
    [data-testid="stHeader"] { background: rgba(247, 246, 239, 0.9); }
    [data-testid="collapsedControl"] { display: none; }
    section.main > div { max-width: 1120px; }
    div[data-testid="stTabs"] button[data-baseweb="tab"] {
        border-radius: 10px 10px 0 0;
        font-weight: 600;
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"],
    div[data-testid="stTabs"] button[data-baseweb="tab"] * {
        color: var(--wasabi-green) !important;
        -webkit-text-fill-color: var(--wasabi-green) !important;
        background-color: #edf1e5 !important;
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"],
    div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] * {
        color: #fff !important;
        -webkit-text-fill-color: #fff !important;
        background-color: var(--wasabi-green) !important;
    }
    .brand-header {
        position: relative;
        overflow: hidden;
        margin: .5rem 0 1.5rem;
        padding: 1.7rem 2rem;
        border: 1px solid #e1e5d7;
        border-radius: 20px;
        background: linear-gradient(115deg, #edf1e5 0%, #f8f5e9 70%, #f1ead8 100%);
    }
    .brand-eyebrow {
        margin: 0 0 .45rem;
        color: var(--wasabi-leaf);
        font-size: .76rem;
        font-weight: 700;
        letter-spacing: .16em;
    }
    .brand-header h1 {
        margin: 0;
        color: var(--wasabi-ink);
        font-family: "Yu Mincho", "Hiragino Mincho ProN", serif;
        font-size: clamp(1.7rem, 4vw, 2.35rem);
        letter-spacing: .04em;
    }
    .brand-header p {
        margin: .55rem 0 0;
        color: #5b6d5e;
        font-size: .94rem;
    }
    .stMarkdown a {
        color: var(--wasabi-green);
        text-decoration-color: #9baa84;
        text-underline-offset: .18em;
    }
    .stMarkdown a:hover {
        color: var(--wasabi-ink);
        text-decoration-color: var(--wasabi-ink);
    }
    div[data-testid="stForm"] {
        padding: 1.2rem 1.35rem .8rem;
        border: 1px solid var(--wasabi-line);
        border-radius: 18px;
        background: rgba(255, 255, 252, .9);
        box-shadow: 0 8px 26px rgba(48, 62, 42, .045);
    }
    div[data-testid="stForm"] h4 {
        color: var(--wasabi-green);
        letter-spacing: .04em;
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
        border-color: #d7ddce;
        border-radius: 10px;
        background-color: #fff !important;
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextInput"] input::placeholder,
    div[data-testid="stSelectbox"] [data-baseweb="select"],
    div[data-testid="stSelectbox"] [data-baseweb="select"] input,
    div[data-testid="stSelectbox"] [data-baseweb="select"] [class*="singleValue"],
    div[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"],
    [data-baseweb="popover"] [role="option"] {
        color: #263a2d !important;
        -webkit-text-fill-color: #263a2d !important;
    }
    div[data-testid="stTextInput"] input::placeholder,
    div[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"] {
        color: #6a7569 !important;
        -webkit-text-fill-color: #6a7569 !important;
        opacity: 1;
    }
    [data-baseweb="popover"] [role="listbox"] {
        background: #fff !important;
    }
    [data-baseweb="popover"] [role="option"]:hover,
    [data-baseweb="popover"] [role="option"][aria-selected="true"] {
        background: #edf1e5 !important;
    }
    div[data-testid="stForm"] button[kind="primary"] {
        background: var(--wasabi-green) !important;
        border: 1px solid var(--wasabi-green) !important;
    }
    div[data-testid="stForm"] button[kind="primary"]:hover {
        background: #324d39 !important;
        border-color: #324d39 !important;
    }
    div[data-testid="stForm"] button[kind="secondary"] {
        background-color: #f0f1e9 !important;
        color: var(--wasabi-ink) !important;
        border: 1px solid #d5dacb !important;
    }
    div[data-testid="stForm"] button[kind="secondary"]:hover {
        background-color: #e4e9dc !important;
        color: #1c2d20 !important;
        border-color: #aab79a !important;
    }
    div[data-testid="stForm"] button[kind="secondary"] p { color: var(--wasabi-ink) !important; }
    div[data-testid="stForm"] button[kind="secondary"]:hover p { color: #1c2d20 !important; }
    h3 { color: var(--wasabi-ink); }
    div[data-testid="stSelectbox"] label,
    div[data-testid="stTextInput"] label { color: #526553; }
    [data-testid="stCaptionContainer"] {
        color: #657365;
        line-height: 1.7;
    }
    .st-key-ingredient-results button[kind="secondary"] {
        background: transparent !important;
        color: #42634a !important;
        border: none !important;
        justify-content: flex-start;
        padding: 0.25rem 0;
        box-shadow: none !important;
        cursor: pointer;
    }
    .st-key-ingredient-results button[kind="secondary"] p {
        color: #42634a !important;
        text-decoration: underline;
        text-underline-offset: 0.15em;
        font-weight: 600;
    }
    .st-key-ingredient-results button[kind="secondary"]:hover p {
        color: #263a2d !important;
    }
    .st-key-ingredient-results button[kind="secondary"]:focus-visible {
        outline: 2px solid #73885b !important;
        outline-offset: 2px;
    }
    .st-key-advice-food-links button[kind="secondary"] {
        min-height: 0;
        padding: 0 !important;
        color: var(--wasabi-green) !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        justify-content: flex-start;
    }
    .st-key-advice-food-links button[kind="secondary"] p {
        color: var(--wasabi-green) !important;
        -webkit-text-fill-color: var(--wasabi-green) !important;
        text-decoration: underline;
        text-underline-offset: 0.15em;
        font-weight: 600;
    }
    .st-key-advice-food-links button[kind="secondary"]:hover p {
        color: var(--wasabi-ink) !important;
        -webkit-text-fill-color: var(--wasabi-ink) !important;
    }
    .st-key-advice-food-links button[kind="secondary"]:focus-visible {
        outline: 2px solid var(--wasabi-leaf) !important;
        outline-offset: 2px;
    }
    .st-key-advice-food-links [data-testid="stHorizontalBlock"] {
        gap: 0.5rem;
    }
    @media (max-width: 900px) {
        .st-key-ingredient-results [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        .st-key-ingredient-results [data-testid="stColumn"] {
            flex: 1 1 30% !important;
            min-width: 30% !important;
        }
    }
    @media (max-width: 560px) {
        section.main > div {
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }
        .brand-header {
            padding: 1.3rem 1.1rem;
            border-radius: 14px;
        }
        .brand-header h1 {
            font-size: 1.55rem;
        }
        div[data-testid="stTabs"] [role="tablist"] {
            flex-wrap: wrap;
            gap: 0.25rem;
        }
        div[data-testid="stTabs"] button[data-baseweb="tab"] {
            flex: 1 1 30%;
            min-width: 0;
            height: auto;
            min-height: 3rem;
            padding: 0.45rem 0.3rem;
            white-space: normal;
        }
        .st-key-ingredient-results [data-testid="stColumn"] {
            flex: 1 1 45% !important;
            min-width: 45% !important;
        }
        .st-key-advice-food-links [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
            gap: 0.3rem;
        }
        .st-key-advice-food-links [data-testid="stColumn"] {
            flex: 1 1 45% !important;
            min-width: 45% !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    ingredients = load_ingredients()
    wellness_entries, symptom_advice_entries = load_wellness_data()
    recipe_entries = load_recipe_data()
except (FileNotFoundError, ValueError) as error:
    st.error(str(error))
    st.stop()

st.markdown(
    """
    <header class="brand-header">
      <div class="brand-eyebrow">WASABI · FOOD &amp; WELLNESS</div>
      <h1>わさびの薬膳辞書</h1>
      <p>季節と体調に寄り添う、食材選びの小さな手引き。</p>
    </header>
    """,
    unsafe_allow_html=True,
)
categories = sorted({item["分類"] for item in ingredients if item.get("分類")})
if WELLNESS_PAGE:
    wellness_tab, recipe_tab, search_tab = st.tabs([
        "養生・薬膳のヒント",
        "薬膳レシピ",
        "食材をさがす",
    ])
    knowledge_tab_position = 1
elif RECIPE_PAGE:
    recipe_tab, wellness_tab, search_tab = st.tabs([
        "薬膳レシピ",
        "養生・薬膳のヒント",
        "食材をさがす",
    ])
    knowledge_tab_position = 1
else:
    search_tab, wellness_tab, recipe_tab = st.tabs([
        "食材をさがす",
        "養生・薬膳のヒント",
        "薬膳レシピ",
    ])
    knowledge_tab_position = 2
st.markdown(
    f"""
    <style>
    div[data-testid="stTabs"] button[data-baseweb="tab"]:nth-of-type({knowledge_tab_position}) {{
        border: 2px solid #73885b !important;
        border-radius: 10px 10px 0 0 !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with search_tab:
    st.markdown("[症状別で探す](?page=wellness)")
    st.markdown("[薬膳レシピを見る](?page=recipe)")
    st.markdown("#### 食材をさがす")
    with st.form("ingredient_search"):
        query = st.text_input(
            "食材名を入力",
            placeholder="食材名を入力（例：しょうが）",
            label_visibility="collapsed",
            help="食材名や別名から検索できます。複数の語句は空白や「、」で区切ると、すべてに一致する食材を探します。",
            key="query_input",
        )
        st.caption("食材名・別名のみを検索します。")
        search_col, clear_col, _ = st.columns([2, 2, 5])
        with search_col:
            search_submitted = st.form_submit_button(
                "検索する", type="primary", use_container_width=True
            )
        with clear_col:
            st.form_submit_button(
                "クリア",
                type="secondary",
                on_click=clear_search,
                use_container_width=True,
            )

    st.caption(
        "情報について：本サイトの内容はAIを活用して作成・整理しています。"
        "各項目の根拠資料を個別に確認できていないため、出典は記載していません。"
        "伝統的な薬膳・養生の考え方を紹介するもので、医療上の助言や診断・治療を目的とするものではありません。"
    )

    if search_submitted:
        st.session_state["submitted_query"] = query
        st.session_state["result_category_input"] = "すべて"
        st.session_state["search_submitted"] = True
        st.session_state["search_results_open"] = True
        st.session_state["selected_ingredient_id"] = ""
        st.session_state["result_page"] = 1

    if st.session_state.get("search_results_open", False):
        show_search_results_dialog(
            ingredients,
            st.session_state.get("submitted_query", ""),
            categories,
        )

with recipe_tab:
    st.markdown("[← 食材をさがす](?page=search)")
    st.markdown("### 🍲 薬膳レシピ")
    st.write("体調に合わせて選びやすい、薬膳の考え方を取り入れた簡単レシピです。")

    recipe_category = st.selectbox(
        "分類",
        ["すべて", *sorted({entry["分類"] for entry in recipe_entries})],
        key="recipe_category_filter",
    )
    recipe_query = st.text_input(
        "悩みや症状から探す",
        placeholder="例：冷え、疲れ、胃腸",
        key="recipe_query",
    ).strip().casefold()
    filtered_recipes = [
        entry for entry in recipe_entries
        if (recipe_category == "すべて" or entry["分類"] == recipe_category)
        and (
            not recipe_query
            or recipe_query in entry["レシピ名"].casefold()
            or recipe_query in entry["主な効能"].casefold()
            or recipe_query in entry["この症状で悩んでいる人におすすめ！"].casefold()
        )
    ]
    st.caption(f"表示：{len(filtered_recipes)}件")
    if not filtered_recipes:
        st.info("条件に合うレシピがありません。絞り込み条件や検索語を変えてください。")
    for entry in filtered_recipes:
        with st.expander(f"{entry['レシピ名']}　·　{entry['分類']}"):
            st.markdown(f"**主な効能：** {entry['主な効能']}")
            st.markdown("**材料**")
            st.write(entry["材料"])
            st.markdown("**作り方**")
            st.write(entry["作り方"])
            st.markdown(f"**ポイント：** {entry['ポイント']}")
            st.caption(
                "おすすめの人："
                f"{entry['この症状で悩んでいる人におすすめ！']}"
            )

with wellness_tab:
    st.markdown("[← 食材をさがす](?page=search)")
    st.markdown("[薬膳レシピを見る](?page=recipe)")
    st.markdown("### 🌿 養生・薬膳のヒント")
    st.write("毎日の暮らしに取り入れやすい、東洋医学と薬膳の基本をまとめました。")

    current_season = {
        3: "春", 4: "春", 5: "春",
        6: "夏", 7: "夏", 8: "夏",
        9: "秋", 10: "秋", 11: "秋",
        12: "冬", 1: "冬", 2: "冬",
    }[date.today().month]
    seasonal_entries = sorted(
        (
            entry for entry in wellness_entries
            if entry["対象季節"] in (current_season, "通年")
        ),
        key=lambda entry: entry["対象季節"] != current_season,
    )[:3]
    st.markdown(f"#### 今の季節のおすすめ（{current_season}）")
    for entry in seasonal_entries:
        with st.expander(entry["タイトル"]):
            st.write(entry["アドバイス本文"])
            st.markdown(f"**おすすめの食材：** {entry['おすすめの食材']}")
            st.caption(entry["ポイント・コツ"])

    st.markdown("#### 症状別おすすめ養生")
    symptom_names = [entry["症状名"] for entry in symptom_advice_entries]
    if "symptom_advice_choice" not in st.session_state:
        st.session_state["symptom_advice_choice"] = "選択してください"
    st.caption("気になる症状を選ぶと、養生法やおすすめ食材が表示されます。")
    selected_advice_name = st.selectbox(
        "気になる症状を選ぶ",
        ["選択してください", *symptom_names],
        key="symptom_advice_choice",
    )
    if selected_advice_name != "選択してください":
        advice = next(
            entry for entry in symptom_advice_entries
            if entry["症状名"] == selected_advice_name
        )
        clicked_recommended_ingredient = None
        with st.container(border=True):
            st.markdown(f"##### {advice['症状名']}")
            st.markdown("**東洋医学で考えられるタイプ**")
            st.write(advice["主な原因・タイプ（東洋医学）"])
            st.markdown("**養生法・アドバイス**")
            st.write(advice["養生法・アドバイス"])
            st.markdown("**おすすめの食材・生薬**")
            recommendations = [
                item.strip()
                for item in re.split(r"[,，、]", advice["おすすめの食材・生薬"])
                if item.strip()
            ]
            with st.container(key="advice-food-links"):
                for row_start in range(0, len(recommendations), 4):
                    columns = st.columns(4)
                    for column_index, recommendation in enumerate(
                        recommendations[row_start : row_start + 4]
                    ):
                        with columns[column_index]:
                            index = row_start + column_index
                            ingredient = find_recommended_ingredient(
                                recommendation, ingredients
                            )
                            if ingredient:
                                if st.button(
                                    recommendation,
                                    key=f"advice-food-{advice['症状ID']}-{index}",
                                    type="secondary",
                                    help="クリックして食材の詳細を表示",
                                    use_container_width=False,
                                ):
                                    clicked_recommended_ingredient = ingredient
                            else:
                                st.markdown(
                                    f"<span style='color:#42634a'>{recommendation}</span>"
                                    " <small>（詳細なし）</small>",
                                    unsafe_allow_html=True,
                                )

            related_recipes = find_related_recipes(selected_advice_name, recipe_entries)
            if related_recipes:
                st.markdown("**関連レシピ**")
                for recipe in related_recipes:
                    with st.container(border=True):
                        st.markdown(
                            f"##### {recipe['レシピ名']}"
                        )
                        st.markdown(f"**分類：** {recipe['分類']}")
                        st.markdown(f"**主な効能：** {recipe['主な効能']}")
                        st.markdown("**材料**")
                        st.write(recipe["材料"])
                        st.markdown("**作り方**")
                        st.write(recipe["作り方"])
                        st.caption(recipe["ポイント"])

            st.markdown("**避けたいこと**")
            st.write(advice["避けたいこと"])
        if clicked_recommended_ingredient:
            show_ingredient_dialog(clicked_recommended_ingredient)

    st.markdown("#### プチ養生一覧")
    list_col, season_col = st.columns(2)
    with list_col:
        selected_wellness_category = st.selectbox(
            "テーマ",
            ["すべて", *sorted({entry["分類"] for entry in wellness_entries})],
            key="wellness_category_filter",
        )
    with season_col:
        selected_season = st.selectbox(
            "季節",
            ["すべて", *sorted(
                {entry["対象季節"] for entry in wellness_entries if entry["対象季節"] != "通年"}
            ), "通年"],
            key="wellness_season_filter",
        )
    wellness_query = st.text_input(
        "悩み・体質から探す",
        placeholder="例：乾燥、冷え、眠り",
        key="wellness_query",
    ).strip().casefold()
    filtered_wellness_entries = [
        entry for entry in wellness_entries
        if (selected_wellness_category == "すべて" or entry["分類"] == selected_wellness_category)
        and (selected_season == "すべて" or entry["対象季節"] in (selected_season, "通年"))
        and (
            not wellness_query
            or wellness_query in entry["タイトル"].casefold()
            or wellness_query in entry["対象の悩み・体質"].casefold()
            or wellness_query in entry["アドバイス本文"].casefold()
        )
    ]
    st.caption(f"表示：{len(filtered_wellness_entries)}件")
    show_filtered_list = bool(
        wellness_query
        or selected_wellness_category != "すべて"
        or selected_season != "すべて"
    )
    with st.expander(
        f"ヒント一覧を見る（{len(filtered_wellness_entries)}件）",
        expanded=show_filtered_list,
    ):
        if not filtered_wellness_entries:
            st.info("条件に合う養生のヒントがありません。検索語や絞り込み条件を変えてください。")
        for entry in filtered_wellness_entries:
            with st.expander(f"{entry['タイトル']}　·　{entry['対象季節']}／{entry['分類']}"):
                st.write(entry["アドバイス本文"])
                st.markdown(f"**対象の悩み・体質：** {entry['対象の悩み・体質']}")
                st.markdown(f"**おすすめの食材：** {entry['おすすめの食材']}")
                st.markdown(f"**ポイント・コツ：** {entry['ポイント・コツ']}")

    st.markdown("#### 東洋医学のミニ知識")
    with st.expander("気・血・津液（しんえき）って？"):
        st.write(
            "東洋医学では、からだを支えるはたらきを「気」、栄養を運ぶものを「血」、"
            "血以外の水分を「津液」と表現します。体調を理解するための伝統的な考え方で、"
            "現代医学の診断用語とは異なります。"
        )
    with st.expander("五性（ごせい）と五味（ごみ）"):
        st.write(
            "五性は食材の性質を寒・涼・平・温・熱に分ける考え方、五味は酸・苦・甘・辛・鹹"
            "（しおからい）の味の分類です。食材詳細の表示は、提供されたデータに基づいています。"
        )
    with st.expander("薬膳は特別な料理が必要？"):
        st.write(
            "薬膳は、季節や日々の体調を意識して食材を選ぶ食養生の考え方です。"
            "身近な食材を使い、無理なく続けられる食事を大切にします。"
        )

    st.markdown("#### 毎日のプチ養生")
    tip_col1, tip_col2 = st.columns(2)
    with tip_col1:
        st.markdown("**食事**")
        st.write("旬の食材を取り入れ、よく噛んで、無理のない量を楽しみましょう。")
    with tip_col2:
        st.markdown("**休息**")
        st.write("睡眠や休憩のリズムを整え、体調に合わせて頑張りすぎないことも大切です。")

    st.divider()
    st.caption(
        "ここでの内容は一般的な情報・セルフケア例で、体質診断や医療上の助言ではありません。"
        "症状が強い、続く、または不安がある場合は医療機関にご相談ください。"
    )
