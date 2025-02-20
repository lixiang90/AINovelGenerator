import re
import os
import time
import datetime
import yaml
import jsonlines
from openai import OpenAI

def separate_thoughts_and_output(text):
    thought_process = re.findall(r'<think>(.*?)</think>', text, re.DOTALL)
    output = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return thought_process[0], output.strip()

def chat(messages, model_args, max_retries=10, pause=20):
    i = 0
    while i < max_retries:
        try:
            client = OpenAI(api_key=model_args['api_key'], base_url=model_args['base_url'])
            response = client.chat.completions.create(
                model=model_args['model'],
                messages=messages,
                stream=False
            )
            if model_args['reasoning']==1:
                think, output = response.choices[0].message.reasoning_content, response.choices[0].message.content
                return {"input":messages,"author":{"base_url":model_args["base_url"],"model":model_args["model"],"reasoning":model_args["reasoning"]},"think":think, "output":output}
            elif model_args['reasoning']==2:
                think, output = separate_thoughts_and_output(response.choices[0].message.content)
                return {"input":messages,"author":{"base_url":model_args["base_url"],"model":model_args["model"],"reasoning":model_args["reasoning"]},"think":think, "output":output}
            else:
                output = response.choices[0].message.content
                return {"input":messages,"author":{"base_url":model_args["base_url"],"model":model_args["model"],"reasoning":model_args["reasoning"]},"output":output}
        except Exception as e:
            #Handle API error here
            print(f"Error: {e}")
            i += 1
            time.sleep(pause)
    print('Max retries exceeded.')
    return -1

def get_utc_timestamp():
    return round(datetime.datetime.now().timestamp() * 1000000)

def split_plan(text):
    plan_list = [item for item in text.split('\n') if len(item)>0 and re.match(r"^第\s?\d+\s?段.*", item)]
    return plan_list

class AgentWriter:
    def __init__(self, config="configs/deepseek-r1.yaml"):
        try:
            with open(config,"r",encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        except FileNotFoundError as e:
            print(f"Error: {e}. \nConfiguration file {config} not found.")
        if "prompt_template" not in self.config:
            raise ValueError("Prompt template not found.")
        try:
            with open(self.config["prompt_template"]["template_plan"],'r',encoding='utf-8') as f:
                self.template_plan = f.read()
        except FileNotFoundError as e:
            print(f"Error: {e}. \nPrompt template file {self.config["prompt_template"]["template_plan"]} not found.")
        try:
            with open(self.config["prompt_template"]["template_write"],'r',encoding='utf-8') as f:
                self.template_write = f.read()
        except FileNotFoundError as e:
            print(f"Error: {e}. \nPrompt template file {self.config["prompt_template"]["template_write"]} not found.")
        if "model_args" not in self.config:
            raise ValueError("Model arguments not found.")
        self.model_args = self.config["model_args"]
        if "retry" in self.config:
            if "max_retries" in self.config["retry"]:
                self.max_retries = self.config["retry"]["max_retries"]
            else:
                self.max_retries = 10
            if "pause" in self.config["retry"]:
                self.pause = self.config["retry"]["pause"]
            else:
                self.pause = 20
        else:
            self.max_retries = 10
            self.pause = 20
        if "save_path" in self.config:
            self.save_path = self.config["save_path"]
        else:
            self.save_path = "generated_texts"
        if "word_requirement" in self.config:
            self.min_word = self.config["word_requirement"]["min_word"]
            self.max_word = self.config["word_requirement"]["max_word"]
            self.sample_1 = self.config["word_requirement"]["sample_1"]
            self.sample_2 = self.config["word_requirement"]["sample_2"]
            assert self.min_word < min(self.sample_1, self.sample_2) < max(self.sample_1, self.sample_2) < self.max_word, "字数设置错误!"
        else:
            self.min_word = 500
            self.max_word = 3000
            self.sample_1 = 800
            self.sample_2 = 2000
        self.status = 'setting'
    
    def set_instruction(self, instruction):
        self.instruction = instruction
        prompt_plan = self.template_plan.replace("$INST$",instruction)
        prompt_plan = prompt_plan.replace("$MIN_WORDS$",str(self.min_word)).replace("$MAX_WORD$",str(self.max_word))
        prompt_plan = prompt_plan.replace("$SAMPLE_1$",str(self.sample_1)).replace("$SAMPLE_2$",str(self.sample_2))
        self.prompt_plan = prompt_plan
        self.prompt_write = self.template_write.replace("$INST$",instruction)
        timestamp = get_utc_timestamp()
        self.work_folder = os.path.join(self.save_path, f"generate_{timestamp}")
        os.makedirs(self.work_folder,exist_ok=True)
        with open(os.path.join(self.work_folder,"instruction.txt"),"w",encoding="utf-8") as f:
            f.write(instruction)
        self.status = 'planning'

    def make_plan(self):
        if self.status == 'setting':
            print("未设定写作指令!")
            return -1
        elif self.status == 'writing':
            print("检测到已生成的大纲，跳过中...")
            return 0
        elif self.status == 'planning':
            print(f"正在为以下写作任务制定大纲：\n{self.instruction}\n")
            messages = [{"role":"user","content":self.prompt_plan}]
            planning_result = chat(messages, model_args=self.model_args, max_retries=self.max_retries, pause=self.pause)
            if planning_result == -1:
                print("大纲生成失败!")
                with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                    f.write("-1")
                return -1
            with jsonlines.open(os.path.join(self.work_folder,"log.jsonl"),'a') as f:
                f.write(planning_result)
            self.plan_text = planning_result["output"]
            with open(os.path.join(self.work_folder,"plan.txt"),'w',encoding='utf-8') as f:
                f.write(self.plan_text)
            self.plan_list = split_plan(self.plan_text)
            self.status = "writing"
            self.N_chapters = len(self.plan_list)
            self.curr_chapter = 0
            self.written = ""
            self.prompt_write = self.template_write.replace("$PLAN$",self.plan_text)
            with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                f.write(0)
            return 0
    
    def write(self):
        assert self.status == "writing", "未找到写作大纲!"
        if self.curr_chapter >= self.N_chapters:
            print(f"写作已完成, 停止生成! 章节数 : {self.N_chapters}")
            return -1
        else:
            print(f"正在写作第{self.curr_chapter+1}段:\n{self.plan_list[self.curr_chapter]}")
            curr_write_prompt = self.prompt_write.replace("$TEXT$",self.written).replace("$STEP$",self.plan_list[self.curr_chapter])
            messages = [{"role":"user","content":curr_write_prompt}]
            try:
                result = chat(messages, self.model_args, self.max_retries, self.pause)
                if result == -1:
                    print(f"第{self.curr_chapter+1}段生成失败!")
                    with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                        f.write(str(self.curr_chapter))
                    return -1
            except KeyboardInterrupt as e:
                print(f"第{self.curr_chapter+1}段生成被用户中止!")
                with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                    f.write(str(self.curr_chapter))
                return -1
            with jsonlines.open(os.path.join(self.work_folder,"log.jsonl"),'a') as f:
                f.write(result)
            with open(os.path.join(self.work_folder, "fulltext.txt"),'a') as f:
                f.write(f'{result['output']}\n\n')
            self.written += f'{result['output']}\n\n'
            print(f"第{self.curr_chapter+1}段生成成功!")
            self.curr_chapter += 1
            with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                f.write(str(self.curr_chapter))
            return 0
    
    def plan_and_write(self, instruction):
        self.set_instruction(instruction)
        code = self.make_plan()
        if code == 0:
            while self.curr_chapter < self.N_chapters:
                code_w = self.write()
                if code_w == -1:
                    break
    
    def continue_from_stop(self, timestamp):
        self.work_folder = os.path.join(self.save_path, f"generate_{timestamp}")
        try:
            with open(os.path.join(self.work_folder,"instruction.txt"),"r",encoding="utf-8") as f:
                self.instruction = f.read()
        except FileNotFoundError as e:
            print(f"Error: {e}. \ninstruction.txt not found.")
        prompt_plan = self.template_plan.replace("$INST$",self.instruction)
        prompt_plan = prompt_plan.replace("$MIN_WORDS$",str(self.min_word)).replace("$MAX_WORD$",str(self.max_word))
        prompt_plan = prompt_plan.replace("$SAMPLE_1$",str(self.sample_1)).replace("$SAMPLE_2$",str(self.sample_2))
        self.prompt_plan = prompt_plan
        self.prompt_write = self.template_write.replace("$INST$",self.instruction)
        with open(os.path.join(self.work_folder,'stop.txt'),'r',encoding='utf-8') as f:
            code = int(f.read())
        if code == -1:
            self.status = "planning"
            code_p = self.make_plan()
            if code_p == 0:
                while self.curr_chapter < self.N_chapters:
                    code_w = self.write()
                    if code_w == -1:
                        break
        else:
            self.status = "writing"
            self.curr_chapter = code
            try:
                with open(os.path.join(self.work_folder,"plan.txt"),"r",encoding="utf-8") as f:
                    self.plan_text = f.read()
            except FileNotFoundError as e:
                print(f"Error: {e}. \nplan.txt not found.")
            if os.path.exists(os.path.join(self.work_folder,"written.txt")):
                with open(os.path.join(self.work_folder,"written.txt"),"r",encoding="utf-8") as f:
                    self.written = f.read()
            else:
                self.written = ""
            self.plan_list = split_plan(self.plan_text)
            self.N_chapters = len(self.plan_list)
            self.prompt_write = self.template_write.replace("$PLAN$",self.plan_text)
            while self.curr_chapter < self.N_chapters:
                code_w = self.write()
                if code_w == -1:
                    break

if __name__ == "__main__":
    writer = AgentWriter()
    introduction = "写一篇10000字左右的名侦探柯南同人小说，讲述主角团来到一座神秘古堡之后，发生了凶杀案，柯南和灰原哀联手查清案件，发现其与二十年前的旧案有关联，并且两人在查案过程中遇到危险，发生感情羁绊的故事。"
    writer.plan_and_write(introduction)
