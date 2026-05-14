from prompt_toolkit.document import Document

from agentx.prompting import SlashCommandCompleter, slash_completion_text


def test_slash_completion_text_keeps_literal_prefix():
    assert slash_completion_text("/config set KEY VALUE") == "/config set "
    assert slash_completion_text("/resume [latest|FILE]") == "/resume "
    assert slash_completion_text("/mode agent") == "/mode agent"


def test_slash_completer_filters_by_prefix():
    completer = SlashCommandCompleter(
        [
            ("/config", "顯示設定"),
            ("/config set KEY VALUE", "寫入設定"),
            ("/mode agent", "agent 模式"),
        ]
    )

    completions = list(completer.get_completions(Document("/config s"), object()))

    assert [completion.text for completion in completions] == ["/config set "]
