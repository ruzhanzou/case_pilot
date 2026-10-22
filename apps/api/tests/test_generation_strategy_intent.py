import pytest

from casepilot_api.generation_strategy import generation_strategy_from_text, is_strategy_question


@pytest.mark.parametrize(
    "text,expected",
    [
        ("测试对象：账号系统，生成登录用例", "generate"),
        ("参考历史用例补充回归", "select_and_generate"),
        ("请复用已有资产", "select_and_generate"),
        ("select", "select"),
        ("SELECT：测试对象账号系统", "select"),
        ("策略：select\n测试对象：账号系统", "select"),
        ("请使用 select_and_generate 生成测试用例", "select_and_generate"),
        ("strategy=select_and_generate", "select_and_generate"),
        ("select是什么意思？", "generate"),
        ("请解释使用select的步骤", "generate"),
        ("不要使用select", "generate"),
        ("不要select，直接生成", "generate"),
        ("selectivity测试", "generate"),
        ("select_and_generate_extra", "generate"),
        ("执行SQL select * from accounts", "generate"),
        ("请总结：```select```", "generate"),
        ("请翻译“使用 select”", "generate"),
        ("策略：select，但不要复用", "generate"),
    ],
)
def test_only_explicit_unambiguous_strategy_directives_enable_reuse(text, expected):
    assert generation_strategy_from_text(text) == expected


def test_strategy_question_is_qa_not_generation():
    assert is_strategy_question("select和select_and_generate有什么区别")


@pytest.mark.parametrize("text,expected", [
    ("找一下已有登录用例，参考后改写", "select_and_generate"),
    ("能帮我找已有登录用例吗？", "select_and_generate"),
    ("选择现有用例组成新集合", "select"),
    ("直接复用已有的登录用例", "select"),
    ("复用已有的，缺少的补齐", "select_and_generate"),
    ("系统支持搜索用例资产吗？", "generate"),
    ("如果找到已有用例，可以复用吗？", "generate"),
    ("不要搜索历史用例，直接生成", "generate"),
    ("请翻译“参考历史用例改写”", "generate"),
    ("生成登录用例", "generate"),
    ("复用已有会话进行登录测试", "generate"),
    ("参照历史用例补充登录场景", "select_and_generate"),
    ("不要改标题，参考已有资产修改步骤", "select_and_generate"),
    ("为青禾系统全新生成用例，不复用历史", "generate"),
    ("能帮我复用已有登录用例吗？", "select_and_generate"),
])
def test_natural_language_asset_authorization(text, expected):
    assert generation_strategy_from_text(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("确认复用", ["a", "b"]), ("只用第一条", ["a"]),
    ("这两条直接用", ["a", "b"]), ("这三条直接用", None),
    ("只用第3条", None), ("不复用，继续生成", []),
    ("确认复用但修改第二条", None), ("那条直接用", None),
])
def test_asset_replies_are_bound_to_displayed_scope(text, expected):
    from casepilot_api.generation_strategy import asset_choice_from_text
    assert asset_choice_from_text(text, ["a", "b"]) == expected


@pytest.mark.parametrize("text,expected", [
    ("帮我找找以前账号登录那块的用例，拿来参考一下", "select_and_generate"),
    ("搜一下登录相关的用例", "select_and_generate"),
    ("有没有现成的登录用例可以参考？", "select_and_generate"),
    ("帮我找类似登录流程的用例参考", "select_and_generate"),
    ("请检索账号认证的测试案例", "select_and_generate"),
    ("不要找以前的用例，重新生成", "generate"),
    ("别搜登录相关用例", "generate"),
    ("如果搜一下登录用例会怎样", "generate"),
    ("请翻译“搜一下登录用例”", "generate"),
    ("为搜索功能生成用例", "generate"),
    ("搜索功能的用例需要覆盖空结果", "generate"),
])
def test_colloquial_search_requires_an_operation_not_a_feature_description(text, expected):
    assert generation_strategy_from_text(text) == expected
