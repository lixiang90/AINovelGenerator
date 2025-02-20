# AgentWriter
本程序使用大语言模型写作万字左右的长篇文本。原理是首先根据用户的指令生成大纲，再根据大纲逐段生成正文。

## 安装必要的软件包
安装python后，使用下列命令安装必要的pip包：
```
pip install -U openai
pip install -U gradio
pip install -U jsonlines
```

## 配置参数
在使用本程序之前，需要先配置参数，并把配置文件保存为 `.yaml` 格式的文件。下面是一个参考配置。

其中 `template_plan` 和 `template_write` 分别是生成大纲和正文的提示词模板。

`min_word` 和 `max_word` 是大纲中各段落的最小和最大字数要求， `sample_1` 和 `sample_2` 则是介于期间的两个字数示例。

`model_args` 是模型参数。其中， `base_url` 是模型的api base，`api_key` 是云服务商提供的base网址，`model` 是模型名称，可能因云服务商而不同，例如deepseek的 `deepseek-reasoner` 在阿里是 `deepseek-r1`. `reasoning` 是模型是否支持思考后再输出，对于没有深度思考功能的模型，应设置为 `0`, 对于有深度思考功能且会输出在 `reasoning_content` 字段的模型，应设置为 `1`, 某些云服务商提供的深度思考模型api没有 `reasoning_content` 字段，而是把深度思考和输出结果以 `<think>思考...</think>输出...` 的格式混合输出到 `content` 字段，此时应把 `reasoning` 设置为 `2`.

`max_retries` 指连接失败后的最大重试次数。`pause` 指重试的间隔时间。

`save_path` 是生成的文本数据的保存位置。实际上，每次生成文本时，会在该文件夹下生成带有时间戳的子文件夹用于存放数据。

```
prompt_template:
    template_plan: "prompts/plan.txt"
    template_write: "prompts/write.txt"
word_requirement:
    min_word: 500
    sample_1: 800
    sample_2: 2000
    max_word: 3000
model_args:
    base_url: "https://api.deepseek.com"
    api_key: "sk-xxxxxx...xxx"
    model: "deepseek-reasoner"
    reasoning: 1
retry:
    max_retries: 10
    pause: 20
save_path: "generated_texts"
```

## 命令行运行
修改 `core_nonstream.py` 的最后几行，然后使用`python core_nonstream.py` 生成完成后即可在您设置的 `save_path` (使用上面的默认配置则是 `generate_texts` ) 文件夹下看到带有时间戳的子文件夹，子文件夹下有指令 (`instruction.txt`), 生成的大纲 ( `plan.txt` ), 正文文本 ( `fulltext.txt` ) 和日志 ( `log.jsonl` )等信息。
```
if __name__ == "__main__":
    writer = AgentWriter(config='你的/配置/文件/路径')
    introduction = "你的写作指令..."
    writer.plan_and_write(introduction)
```

## 图形界面运行
使用 `python app.py -c '你的/配置/文件/路径'` （或把 `app.py` 第8行的default参数值修改为你的配置文件路径）后在浏览器打开相应网页，即可看到运行界面。

使用步骤：
1. 先输入用户指令，然后点击“生成大纲”，程序会首先在折叠（可展开）的生成日志下生成思维过程，然后把文章大纲显示在左侧的表格上。
2. 接下来，点击“生成段落”即可逐段生成正文内容并输出到右侧文本框。当然，每次也是先生成思维过程，再生成内容。
3. 如果点击“生成全文”，就会连续生成其余全部段落。
4. 再次输入用户指令并点击“生成大纲”会清除之前生成的内容并重新生成。如果之前的内容没有保存，可以在您设置的 `save_path` (使用上面的默认配置则是 `generate_texts` ) 文件夹下找到带有时间戳的子文件夹，该子文件夹下已经保存了相应数据。


