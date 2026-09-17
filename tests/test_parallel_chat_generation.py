import argparse
import asyncio
from pathlib import Path

from test_chat_revamp import browser


MLX_MODEL = "local:mlx:llama-3.2-11b-vision-instruct"
GEMMA_MODEL = (
    "local:huggingface:google/gemma-4-12B-it-qat-q4_0-gguf@"
    "29d097773436b69ff9feafd636ab4cf873786537:Q4_0"
)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument(
        "--artifacts", type=Path, default=Path("/tmp/ark_parallel_chat")
    )
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    async with browser(args.binary.resolve(), artifacts) as cdp:
        page = await cdp.first_page()
        await cdp.navigate(page, "ark://ark-chat/#chat")
        await cdp.wait_for(page, "!!window.__arkTest")
        await cdp.wait_for(
            page,
            f"!!document.querySelector('[data-model-value=\"{MLX_MODEL}\"]') "
            f"&& !!document.querySelector('[data-model-value=\"{GEMMA_MODEL}\"]')",
            timeout=30,
        )

        started = await cdp.evaluate(
            page,
            f"""(async () => {{
              const test = window.__arkTest;
              const chooseModel = async (menuId, model) => {{
                const option = document.querySelector(
                    `#${{menuId}} [data-model-value="${{model}}"]`);
                if (!option) throw new Error(`Missing model option: ${{model}}`);
                option.click();
                await new Promise(resolve => setTimeout(resolve, 100));
              }};

              test.createNewChat();
              await chooseModel('composer-model-menu', {GEMMA_MODEL!r});
              document.querySelector('#draft').value =
                  'Explain in one sentence why the sky looks blue.';
              window.parallelGemma = test.sendMessage();

              for (let i = 0; i < 100 &&
                   test.getGeneratingConversationIds().length !== 1; i++) {{
                await new Promise(resolve => setTimeout(resolve, 50));
              }}
              const firstConversationId =
                  test.getGeneratingConversationIds()[0] || '';

              location.hash = 'home';
              await new Promise(resolve => setTimeout(resolve, 100));
              document.querySelector('#ai-mode').click();
              await chooseModel('home-model-menu', {MLX_MODEL!r});
              const search = document.querySelector('#search-input');
              search.value = 'Reply in one sentence: what is a browser?';
              document.querySelector('#search-form').requestSubmit();

              for (let i = 0; i < 200 &&
                   test.getGeneratingConversationIds().length !== 2; i++) {{
                await new Promise(resolve => setTimeout(resolve, 50));
              }}
              const activeIds = test.getGeneratingConversationIds();
              const secondConversationId = activeIds.find(
                  id => id !== firstConversationId) || '';

              const {{PageHandler}} = await import('./ark.mojom-webui.js');
              const duplicate = await PageHandler.getRemote().sendChatPrompt(
                  firstConversationId,
                  'This direct duplicate must also be rejected.', null, null);

              await test.switchToConversation(firstConversationId);
              document.querySelector('#draft').value =
                  'This message must not be accepted while the chat is busy.';
              await test.sendMessage();

              return {{
                firstConversationId,
                secondConversationId,
                activeIds: test.getGeneratingConversationIds(),
                duplicate,
                route: location.hash,
              }};
            }})()""",
        )
        assert started["firstConversationId"], "Gemma chat did not start"
        assert started["secondConversationId"], "Ask AI did not create a new chat"
        assert len(started["activeIds"]) == 2, started
        assert not started["duplicate"]["success"], started["duplicate"]
        assert "already generating" in started["duplicate"]["response"], started
        assert started["route"] == "#chat", started
        print("PASS 1: Gemma chat and Ask AI MLX chat generate concurrently")

        await cdp.wait_for(
            page,
            "window.__arkTest.getGeneratingConversationIds().length === 0",
            timeout=1200,
        )
        result = await cdp.evaluate(
            page,
            f"""(async () => {{
              const {{PageHandler}} = await import('./ark.mojom-webui.js');
              const remote = PageHandler.getRemote();
              const conversations = (await remote.getConversations()).conversations;
              const inspect = async id => {{
                const conversation = conversations.find(item => item.id === id);
                const messages = (await remote.getMessages(id)).messages;
                return {{
                  title: conversation?.title || '',
                  users: messages.filter(item => item.role === 'user')
                      .map(item => item.content),
                  assistants: messages.filter(item => item.role === 'assistant')
                      .map(item => ({{model: item.modelName, content: item.content}})),
                }};
              }};
              return {{
                gemma: await inspect({started['firstConversationId']!r}),
                mlx: await inspect({started['secondConversationId']!r}),
              }};
            }})()""",
        )

        assert result["gemma"]["users"] == [
            "Explain in one sentence why the sky looks blue."
        ], result["gemma"]
        assert result["mlx"]["users"] == [
            "Reply in one sentence: what is a browser?"
        ], result["mlx"]
        assert len(result["gemma"]["assistants"]) == 1, result["gemma"]
        assert len(result["mlx"]["assistants"]) == 1, result["mlx"]
        assert result["gemma"]["assistants"][0]["model"] == GEMMA_MODEL
        assert result["mlx"]["assistants"][0]["model"] == MLX_MODEL
        assert result["gemma"]["title"] not in ("", "New conversation")
        assert result["mlx"]["title"] not in ("", "New conversation")
        print("PASS 2: Responses, models, and generated titles stayed isolated")
        print("PASS 3: A second send in the busy Gemma chat was rejected")

        cloud = await cdp.evaluate(
            page,
            """(async () => {
              const {PageHandler} = await import('./ark.mojom-webui.js');
              const remote = PageHandler.getRemote();
              const {state} = await remote.createConversation(
                  'cloud:gemini-2.5-flash');
              const result = await remote.sendChatPrompt(
                  state.id, 'hello', null, null);
              const messages = (await remote.getMessages(state.id)).messages;
              await remote.deleteConversation(state.id);
              return {result, messageCount: messages.length};
            })()""",
        )
        assert not cloud["result"]["success"], cloud
        assert "API key is missing" in cloud["result"]["response"], cloud
        assert cloud["messageCount"] == 0, cloud
        print("PASS 4: Gemini routes through the service and rejects safely")


if __name__ == "__main__":
    asyncio.run(main())
