# RAG Evaluation Report

- Eval file: `backend\eval\rag_eval_set.local.jsonl`
- Cases: 12
- Runnable cases: 12
- Skipped cases: 0

## Metrics

- Recall@3: 0.8206
- Recall@5: 0.8444
- MRR: 0.9167
- Evidence Hit Rate: 1.0

## Cases

### zh_ssvep_01_paradigm

- Query: 这篇中文赛题文档中的 SSVEP 键盘拼写刺激范式是什么？它和典型 cVEP/SSVEP 区分中提到的编码刺激有什么关系？
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 0.6667
- Recall@5: 0.6667
- MRR: 1.0
- Top evidence section: 实验范式为键盘拼写，刺激范式如图1 所示。实验采用on 型刺激，图1 中每个目标的
- Top evidence score: 1

### zh_ssvep_02_narrowband_sequence

- Query: 窄带随机编码序列如何设置？请说明 15~25Hz、120 Hz 刷新率、120 帧和 Sequence.npy 的作用。
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 1.0
- Recall@5: 1.0
- MRR: 1.0
- Top evidence section: 实验范式为键盘拼写，刺激范式如图1 所示。实验采用on 型刺激，图1 中每个目标的
- Top evidence score: 5

### zh_ssvep_03_experiment_data

- Query: 中文 SSVEP 赛题的数据采集和实验设置是什么，包括 EEG 通道、trigger、采样率和降采样？
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 1.0
- Recall@5: 1.0
- MRR: 1.0
- Top evidence section: 实验范式为键盘拼写，刺激范式如图1 所示。实验采用on 型刺激，图1 中每个目标的 (1)
- Top evidence score: 3

### zh_ssvep_04_online_interface

- Query: 模拟在线评测中算法怎样通过 ProblemInterface 读取数据和报告分类结果？
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 1.0
- Recall@5: 1.0
- MRR: 1.0
- Top evidence section: (2)
- Top evidence score: 1

### zh_ssvep_05_metric_itr

- Query: 中文赛题如何评价分类方法效果？ITR、平均试次时长、目标数和正确率之间是什么关系？
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 1.0
- Recall@5: 1.0
- MRR: 1.0
- Top evidence section: 其中，T 表示平均试次时长，M 表示目标个数，P 表示识别正确率。ITR 的单位是bits/min。
- Top evidence score: 1

### zh_ssvep_06_limitations

- Query: 这篇中文 SSVEP 赛题文档有哪些局限性，尤其是关于基线算法、被试信息和随机编码生成细节？
- Paper ID: `paper_e2e2a2580ff54f40`
- Hit: True
- First relevant rank: 1
- Recall@3: 0.3333
- Recall@5: 0.3333
- MRR: 1.0
- Top evidence section: 实验范式为键盘拼写，刺激范式如图1 所示。实验采用on 型刺激，图1 中每个目标的
- Top evidence score: 1

### en_ssvep_01_ssvep_vs_cvep

- Query: In the English paper, how is SSVEP positioned relative to code-like visual encoding ideas such as cVEP, and what is the main BCI communication goal?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 1
- Recall@3: 0.6667
- Recall@5: 0.6667
- MRR: 1.0
- Top evidence section: Results
- Top evidence score: 6

### en_ssvep_02_fdm_encoding

- Query: What encoding sequence or stimulation strategy does the English paper use for high-density frequency division multiplexing of SSVEPs?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 1
- Recall@3: 0.8333
- Recall@5: 0.8333
- MRR: 1.0
- Top evidence section: Results
- Top evidence score: 9

### en_ssvep_03_intermodulation

- Query: How does the paper use intermodulation frequencies and NPSD evidence to describe nonlinear visual responses?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 2
- Recall@3: 0.7143
- Recall@5: 1.0
- MRR: 0.5
- Top evidence section: Results (2)
- Top evidence score: 7

### en_ssvep_04_image_transmission_results

- Query: What experiment and result metrics are reported for image transmission, including MNIST digits and SSIM?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 1
- Recall@3: 0.8333
- Recall@5: 0.8333
- MRR: 1.0
- Top evidence section: Results (2)
- Top evidence score: 8

### en_ssvep_05_classification_method

- Query: What classification method is used in the English paper for the Iris dataset demonstration, and how is PNN classification discussed?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 2
- Recall@3: 0.8
- Recall@5: 0.8
- MRR: 0.5
- Top evidence section: Methods
- Top evidence score: 4

### en_ssvep_06_limitations_attention

- Query: What limitations or human-centred constraints does the English paper discuss, including attention, focus disruption and acquisition time?
- Paper ID: `paper_64f99d33a5e5438f`
- Hit: True
- First relevant rank: 1
- Recall@3: 1.0
- Recall@5: 1.0
- MRR: 1.0
- Top evidence section: Discussion (2)
- Top evidence score: 8

## Skipped Cases

No skipped cases.
