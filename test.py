import gradio as gr
import time

def stream_text():
    for i in range(5):
        time.sleep(1)  # 模拟延迟
        yield f"这是第 {i+1} 行文本\n"

# 创建Gradio界面
with gr.Blocks() as demo:
    text_box = gr.Textbox(label="流式文本输出", interactive=False)
    btn = gr.Button("开始输出")
    
    btn.click(stream_text, outputs=text_box)

demo.launch()
