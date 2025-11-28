import os
from vllm import LLM, SamplingParams

# 配置模型路径
# 用户指定模型目录: /Volumes/data/models/Qwen3-0.6B
# vLLM 将尝试从该目录加载模型 (需包含 config.json, tokenizer.json, model.safetensors 等文件)
MODEL_PATH = "/Volumes/data/models/qwen/Qwen2.5-0.5B-Instruct"

def main():
    # 1. 准备提示词 (Prompts)
    # 这里我们准备几个测试问题
    prompts = [
        "Hello, who are you?",
        "请介绍一下你自己。",
        "写一首关于春天的七言绝句。",
        "Explain the concept of quantum entanglement in simple terms."
    ]

    # 2. 设置采样参数 (Sampling Params)
    # temperature: 控制输出的随机性，0.0 表示确定性输出
    # top_p: 核采样参数
    # max_tokens: 最大生成长度
    sampling_params = SamplingParams(
        temperature=0.7,
        top_p=0.8,
        max_tokens=512,
        stop=["<|endoftext|>", "<|im_end|>"] # 设置停止符，防止生成多余内容
    )

    print(f"正在加载模型: {MODEL_PATH} ...")

    try:
        # 3. 初始化 vLLM 引擎
        # tensor_parallel_size: 如果您有多张显卡，可以设置为显卡数量
        llm = LLM(
            model=MODEL_PATH,
            tensor_parallel_size=1,
            max_model_len=4096, # 限制最大上下文长度
            tokenizer_mode="slow", # 尝试使用慢速分词器以避开 fast tokenizer 的潜在问题
            enforce_eager=True # 强制使用 eager 模式，避免 CPU 上的 torch.compile 错误
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"模型加载失败: {e}")
        return

    print("模型加载成功，开始生成...")

    # 4. 执行生成
    outputs = llm.generate(prompts, sampling_params)

    # 5. 输出结果
    for output in outputs:
        prompt = output.prompt
        generated_text = output.outputs[0].text
        print(f"\n{'='*20}\nPrompt: {prompt!r}\nGenerated: {generated_text!r}\n{'='*20}")

if __name__ == "__main__":
    main()
