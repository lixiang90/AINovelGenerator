import argparse
import gradio as gr
from core_stream import AgentWriter

def start():
    """Initialize configuration file."""
    parser = argparse.ArgumentParser("读取配置文件，载入应用")
    parser.add_argument("-c","--config",type=str,default="configs/deepseek-r1.yaml",help="配置文件路径")
    args = parser.parse_args()
    return args.config

def stream_planning(instruction):
    agent.set_instruction(instruction)
    result = agent.make_plan()
    if result == -1:
        print("生成大纲失败!")
        yield gr.update(), gr.update(), gr.update(), gr.update()
    elif result == 0:
        print("生成大纲成功!")
        yield gr.update(), gr.update(), gr.update(), gr.update()
    else:
        yield gr.update(), gr.update(), gr.update(value=""), gr.update(value="生成段落(第1段)")
        for status, think, chapter in result:
            if status == 'think':
                yield gr.update(value=think), gr.update(), gr.update(), gr.update()
            elif status == 'output':
                table_data = [[ch['段落'],ch['要点描述'],ch['字数要求']] for ch in chapter]
                yield gr.update(value=think), gr.update(value=table_data), gr.update(), gr.update()

def stream_writing(think_data, table_data, text_data):
    assert agent.status == 'writing', '尚未生成大纲!'
    agent.plan_list = [f"第 {item[0]} 段 - 要点：{item[1]} - 字数：{item[2]}" for item in table_data.values]
    agent.plan_text = '\n'.join(agent.plan_list)
    if not think_data:
        think_data = ""
    original_think = think_data + '<br>'
    if agent.curr_chapter > 0:
        original_text = text_data + '\n\n'
    else:
        original_text = text_data
    writer = agent.write()
    if writer == -1:
        return gr.update(), gr.update(), gr.update()
    if agent.model_args["reasoning"] == 2:
        for state, think, text in writer:
            yield gr.update(value=original_think+think), gr.update(value=original_text+text), gr.update()
    else:
        for state, text in writer:
            if state == "think":
                yield gr.update(value=original_think+text), gr.update(), gr.update()
            elif state == "output":
                yield gr.update(), gr.update(value=original_text+text), gr.update()
    yield gr.update(), gr.update(), gr.update(value = f"生成段落(第{agent.curr_chapter+1}段)")

def stream_writing_all(think_data, table_data, text_data):
    assert agent.status == 'writing', '尚未生成大纲!'
    agent.plan_list = [f"第 {item[0]} 段 - 要点：{item[1]} - 字数：{item[2]}" for item in table_data.values]
    agent.N_chapters = len(agent.plan_list)
    agent.plan_text = '\n'.join(agent.plan_list)
    if not think_data:
        think_data = ""
    if not text_data:
        text_data = ""
    original_think = think_data + '<br>'
    if agent.curr_chapter > 0:
        original_text = text_data + '\n\n'
    else:
        original_text = text_data
    if agent.curr_chapter >= agent.N_chapters:
        yield gr.update(), gr.update(), gr.update()
    else:
        for _ in range(agent.curr_chapter,agent.N_chapters):
            writer = agent.write()
            if writer == -1:
                yield gr.update(), gr.update(), gr.update()
                break
            if agent.model_args["reasoning"] == 2:
                curr_think, curr_text = "", ""
                for state, think, text in writer:
                    if not think:
                        think = ""
                    if not text:
                        text = ""
                    curr_think, curr_text = think, text
                    yield gr.update(value=original_think+think), gr.update(value=original_text+text), gr.update()
            else:
                curr_think, curr_text = "", ""
                for state, text in writer:
                    if not text:
                        text = ""
                    if state == "think":
                        curr_think = text
                        yield gr.update(value=original_think+text), gr.update(), gr.update()
                    elif state == "output":
                        curr_text = text
                        yield gr.update(), gr.update(value=original_text+text), gr.update()
            yield gr.update(), gr.update(), gr.update(value = f"生成段落(第{agent.curr_chapter+1}段)")
            original_think += curr_think + '<br>'
            original_text += curr_text + "\n\n"
            

config = start()
agent = AgentWriter(config)

with gr.Blocks(theme='soft', title="小说生成器") as demo:
    gr.Markdown("## <center>📖 AI小说生成器</center>")
    
    with gr.Row():
        input_prompt = gr.Textbox(
            label="请输入创作指令",
            placeholder="例如：生成一个科幻题材的悬疑小说...",
            lines=3
        )
    
    with gr.Row():
        submit_btn = gr.Button("生成大纲", variant="primary", scale=2)
        generate_chapter_btn = gr.Button("生成段落(第1段)", variant="huggingface", scale=1)
        generate_btn = gr.Button("生成全文", variant="secondary", scale=1) 
    
    with gr.Accordion("生成日志", open=False):
        thinking_process = gr.HTML(label="思考过程")
    with gr.Row(equal_height=True):
        output_table = gr.Dataframe(
            headers=["段落", "要点描述", "字数"],
            datatype=["str", "str", "str"],
            col_count=(3, "fixed"),
            interactive=True,
            label="大纲",
            column_widths=["15%", "75%", "10%"],
            wrap=True
        )
        output_text = gr.TextArea(placeholder='文章正文...',label='全文',show_copy_button=True, lines=30)
    
    submit_btn.click(
        fn=stream_planning,
        inputs=input_prompt,
        outputs=[thinking_process, output_table, output_text, generate_chapter_btn]
    )

    generate_chapter_btn.click(
        fn=stream_writing,
        inputs=[thinking_process,output_table,output_text],
        outputs=[thinking_process, output_text, generate_chapter_btn]
    )

    generate_btn.click(
        fn=stream_writing_all,
        inputs=[thinking_process,output_table,output_text],
        outputs=[thinking_process, output_text, generate_chapter_btn]
    )

if __name__ == "__main__":
    demo.launch()
