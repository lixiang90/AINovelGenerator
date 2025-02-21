import time
import re
import datetime
import os
from openai import OpenAI
import yaml
import jsonlines

def stream(messages, model_args, max_retries=10, pause=20):
    i = 0
    while i < max_retries:
        try:
            client = OpenAI(api_key=model_args["api_key"], base_url=model_args["base_url"])
            response = client.chat.completions.create(
                model=model_args["model"],
                messages=messages,
                stream=True
            )
            for chunk in response:        
                if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                    reasoning_content = chunk.choices[0].delta.reasoning_content
                    if not reasoning_content:
                        reasoning_content = ""
                    yield {'think': reasoning_content}
                else:
                    content = chunk.choices[0].delta.content
                    if not content:
                        content = ""
                    yield {'output': content}
            break
        except Exception as e:
            #Handle API error here
            print(f"Error: {e}")
            i += 1
            time.sleep(pause)
    if i >= max_retries:
        print('Max retries exceeded.')
        return -1

def get_utc_timestamp():
    return round(datetime.datetime.now().timestamp() * 1000000)

def split_plan(text):
    plan_list = [item for item in text.split('\n') if len(item)>0 and re.match(r"^第\s?\d+\s?段.*", item)]
    return plan_list

def parse_line(line):
    line = line.strip()
    num = re.search(r"第\s*(\d+)\s*段",line)
    if not num:
        return None
    num = num.group(1)
    if '要点' not in line:
        return {'段落':num,'要点描述':'生成中...','字数要求':'计算中...'}
    content = re.search(r"\s*-?\s*要点[:：](.*)", line)
    if content:
        wordcount = re.search(r"\s?-?\s?(字数)?[:：]?\s*(\d+)\s*字$", line)
        if wordcount:
            words = wordcount.group(0)
            passage = content.group(1)
            passage = re.sub(f'{words}$','',passage)
            if wordcount.group(2):
                return {'段落':num,'要点描述':passage,'字数要求':wordcount.group(2) + '字'}
            else:
                return {'段落':num,'要点描述':passage,'字数要求':''}
        return {'段落':num,'要点描述':content.group(1),'字数要求':'计算中...'}

def parse_text(text):
    all_lines = [line.strip() for line in text.split('\n') if len(line)>0]
    line_nums = [i for i,line in enumerate(all_lines) if re.match(r"^第\s?\d+\s?段.*", line)]
    if len(line_nums) == 0:
        return []
    lines = [all_lines[line_nums[i]:line_nums[i+1]] for i in range(len(line_nums)-1)]
    lines.append(all_lines[line_nums[-1]:])
    lines = ['\n'.join(line) for line in lines]
    data = []
    for line in lines:
        parsed_line = parse_line(line)
        if parsed_line:
            data.append(parsed_line)
    return data

class StreamProcessorForPlanning:
    def __init__(self):
        self.think = ''
        self.chapters = []
        self.buffer = ''
        self.status = 'think'
    
    def process_chunk_for_planning(self, chunk):
        if 'think' in chunk:
            if chunk['think']:
                self.status = 'think'
                self.think += chunk['think']
        elif 'output' in chunk:
            if chunk['output']:
                if self.status == 'think':
                    self.think += '\n\n'
                self.status = 'output'
                self.buffer += chunk['output']
            self.chapters = parse_text(self.buffer)
    
    def process_chunk_for_planning_2(self, chunk):
        """For those apis (e.g. baidu's deepseek-r1 api) that use <think></think> to markup chain of throught (model_args['reasoning']==2)"""
        if 'output' in chunk:
            if chunk['output']:
                self.buffer += chunk['output']
                if self.status == 'output':
                    self.chapters = parse_text(self.buffer)
                elif self.status == 'think':
                    if '<think>' in self.buffer:
                        thought_process = re.findall(r'<think>(.*?)</think>', self.buffer, re.DOTALL)
                        if len(thought_process) == 0:
                            self.think = re.search(r"<think>(.*)", self.buffer).group(1)
                        else:
                            self.status = 'output'
                            self.think = thought_process[0]
                            self.buffer = re.sub(r'<think>.*?</think>', '', self.buffer, flags=re.DOTALL).strip()

class StreamProcessorForWriting:
    def __init__(self):
        self.think = ''
        self.text = ''
        self.delta_think = ''
        self.delta_text = ''
        self.status = 'think'
        self.buffer = ''

    def process_chunk_for_writing(self, chunk):
        if 'think' in chunk:
            if chunk['think']:
                self.status = 'think'
                self.delta_think = chunk['think']
                self.think += chunk['think']
        elif 'output' in chunk:
            if chunk['output']:
                if self.status == 'think':
                    self.think += '\n\n'
                self.status = 'output'
                self.delta_text = chunk['output']
                self.text += chunk['output']

    def process_chunk_for_writing_2(self, chunk):
        """For those apis (e.g. baidu's deepseek-r1 api) that use <think></think> to markup chain of throught (model_args['reasoning']==2)"""
        if 'output' in chunk:
            if chunk['output']:
                if self.status == 'output':
                    self.delta_text = chunk['output']
                    self.text += chunk['output']
                elif self.status == 'think':
                    self.buffer += chunk['output']
                    if '<think>' in self.buffer:
                        thought_process = re.findall(r'<think>(.*?)</think>', self.buffer, re.DOTALL)
                        if len(thought_process) == 0:
                            self.think = re.search(r"<think>(.*)", self.buffer).group(1)
                        else:
                            self.status = 'output'
                            self.buffer = ''
                            self.think = thought_process[0]
                            self.text = re.sub(r'<think>.*?</think>', '', self.buffer, flags=re.DOTALL).strip()


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
        prompt_plan = prompt_plan.replace("$MIN_WORDS$",str(self.min_word)).replace("$MAX_WORDS$",str(self.max_word))
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
            planning_result = stream(messages, model_args=self.model_args, max_retries=self.max_retries, pause=self.pause)
            if planning_result == -1:
                print("大纲生成失败!")
                with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                    f.write("-1")
                return -1
            processor = StreamProcessorForPlanning()
            if self.model_args['reasoning'] == 2:
                for chunk in planning_result:
                    processor.process_chunk_for_planning_2(chunk)
                    yield processor.status, processor.think, processor.chapters
            else:
                for chunk in planning_result:
                    processor.process_chunk_for_planning(chunk)
                    yield processor.status, processor.think, processor.chapters
            planning_result = {
                                    "input":messages,
                                    "author":{"base_url":self.model_args["base_url"],
                                            "model":self.model_args["model"],
                                            "reasoning":self.model_args["reasoning"]},
                                    "think":processor.think, 
                                    "output":'\n'.join([f"第 {item['段落']} 段 - 要点：{item['要点描述']} - 字数：{item['字数要求']}" for item in processor.chapters])
                                }
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
            with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                f.write('0')
            print("生成大纲成功!")
            self.status = 'writing'
            return 0

    def write(self):
        assert self.status == "writing", "未找到写作大纲!"
        if self.curr_chapter >= self.N_chapters:
            print(f"写作已完成, 停止生成! 章节数 : {self.N_chapters}")
            return -1
        else:
            print(f"正在写作第{self.curr_chapter+1}段:\n{self.plan_list[self.curr_chapter]}")
            curr_write_prompt = self.template_write.replace("$PLAN$",self.plan_text).replace("$TEXT$",self.written).replace("$STEP$",self.plan_list[self.curr_chapter])
            messages = [{"role":"user","content":curr_write_prompt}]
            try:
                result = stream(messages, self.model_args, self.max_retries, self.pause)
                if result == -1:
                    print(f"第{self.curr_chapter+1}段生成失败!")
                    with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                        f.write(str(self.curr_chapter))
                    return -1
                processor = StreamProcessorForWriting()
                if self.model_args['reasoning'] == 2:
                    for chunk in result:
                        processor.process_chunk_for_writing_2(chunk)
                        yield processor.status, processor.think, processor.text
                else:
                    for chunk in result:
                        processor.process_chunk_for_writing(chunk)
                        if processor.status == 'think':
                            yield processor.status, processor.think
                        elif processor.status == 'output':
                            yield processor.status, processor.text
            except KeyboardInterrupt as e:
                print(f"第{self.curr_chapter+1}段生成被用户中止!")
                with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                    f.write(str(self.curr_chapter))
                return -1
            result = {
                        "input":messages,
                        "author":{"base_url":self.model_args["base_url"],
                                "model":self.model_args["model"],
                                "reasoning":self.model_args["reasoning"]},
                        "think":processor.think, 
                        "output":processor.text
                    }
            with jsonlines.open(os.path.join(self.work_folder,"log.jsonl"),'a') as f:
                f.write(result)
            with open(os.path.join(self.work_folder, "fulltext.txt"),'a',encoding='utf-8') as f:
                f.write(f'{result['output']}\n\n')
            self.written += f'{result['output']}\n\n'
            print(f"第{self.curr_chapter+1}段生成成功!")
            self.curr_chapter += 1
            with open(os.path.join(self.work_folder,'stop.txt'),'w',encoding='utf-8') as f:
                f.write(str(self.curr_chapter))
