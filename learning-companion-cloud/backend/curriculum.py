from __future__ import annotations

from typing import Any


WUHAN_DEFAULTS = {
    "city": "武汉",
    "grade": "五年级",
    "semester": "上册",
    "chinese_version": "统编版/人民教育出版社",
    "math_version": "北师大版/北京师范大学出版社",
    "english_version": "外研社三年级起点/刘兆义",
}


CURRICULUM: dict[str, list[dict[str, Any]]] = {
    "chinese": [
        {
            "unit": "第一单元：万物有灵",
            "lessons": ["白鹭", "落花生", "桂花雨", "珍珠鸟"],
            "points": ["借物抒情", "对比描写", "细节描写", "围绕中心表达"],
            "quiz_focus": ["概括主要内容", "体会关键句含义", "仿写一段观察描写"],
            "scope_note": "只考阅读理解、表达方法和习作能力，不要求背诵课文全文。",
        },
        {
            "unit": "第二单元：阅读要有速度",
            "lessons": ["搭石", "将相和", "什么比猎豹的速度更快", "冀中的地道战"],
            "points": ["提高阅读速度", "抓关键词句", "概括事件", "说明方法初步感知"],
            "quiz_focus": ["限时概括", "排序事件", "提取关键信息"],
            "scope_note": "重点训练速度和信息提取，不扩展到课外历史细节。",
        },
        {
            "unit": "第三单元：民间故事",
            "lessons": ["猎人海力布", "牛郎织女（一）", "牛郎织女（二）"],
            "points": ["复述故事", "缩写故事", "人物品质", "民间故事特点"],
            "quiz_focus": ["按起因经过结果复述", "人物评价", "缩写片段"],
            "scope_note": "围绕教材民间故事能力点，不引入复杂文学史。",
        },
        {
            "unit": "第四单元：家国情怀",
            "lessons": ["古诗三首", "少年中国说（节选）", "圆明园的毁灭", "小岛"],
            "points": ["资料辅助理解", "情感体会", "场景描写", "有感情朗读"],
            "quiz_focus": ["解释关键句", "概括情感", "写一段读后感"],
            "scope_note": "不要求超出五年级理解水平的历史展开。",
        },
        {
            "unit": "第五单元：说明文",
            "lessons": ["太阳", "松鼠"],
            "points": ["列数字", "作比较", "打比方", "抓住事物特点"],
            "quiz_focus": ["判断说明方法", "提取说明对象特点", "写一个说明片段"],
            "scope_note": "重点在说明方法和表达，不考复杂科学知识。",
        },
        {
            "unit": "第六单元：父母之爱",
            "lessons": ["慈母情深", "父爱之舟", "“精彩极了”和“糟糕透了”"],
            "points": ["场景描写", "细节描写", "体会情感", "联系生活表达"],
            "quiz_focus": ["分析细节作用", "概括情感变化", "写生活片段"],
            "scope_note": "只围绕情感理解和表达，不做价值观说教题。",
        },
        {
            "unit": "第七单元：四时景物",
            "lessons": ["古诗词三首", "四季之美", "鸟的天堂", "月迹"],
            "points": ["静态动态描写", "景物顺序", "想象画面", "优美语句积累"],
            "quiz_focus": ["判断描写方法", "补写景物片段", "体会画面感"],
            "scope_note": "不要求背诵未指定内容。",
        },
        {
            "unit": "第八单元：读书明智",
            "lessons": ["古人谈读书", "忆读书", "我的“长生果”"],
            "points": ["理解读书方法", "梳理观点", "联系实际", "推荐一本书"],
            "quiz_focus": ["概括观点", "说清读书方法", "写推荐理由"],
            "scope_note": "围绕教材读书方法，不扩展到高年级议论文写作。",
        },
    ],
    "math_bsd": [
        {
            "unit": "第一单元：小数除法",
            "lessons": ["精打细算", "打扫卫生", "谁打电话的时间长", "人民币兑换", "除得尽吗", "调查生活垃圾"],
            "points": ["小数除以整数", "除数是小数的除法", "商的近似值", "循环小数", "解决实际问题"],
            "quiz_focus": ["竖式计算", "小数点移动", "估算与验算", "生活应用题"],
            "scope_note": "按五上小数除法难度出题，不提前引入分式或初中代数。",
        },
        {
            "unit": "第二单元：轴对称和平移",
            "lessons": ["轴对称再认识", "平移"],
            "points": ["对称轴", "补全轴对称图形", "平移方向", "平移格数"],
            "quiz_focus": ["判断对称轴", "描述平移", "补全图形步骤"],
            "scope_note": "文字题为主，复杂作图留给纸笔完成。",
        },
        {
            "unit": "第三单元：倍数与因数",
            "lessons": ["倍数与因数", "2、5 的倍数特征", "3 的倍数特征", "找因数", "找质数"],
            "points": ["倍数", "因数", "奇偶数", "质数合数", "2/3/5 倍数特征"],
            "quiz_focus": ["判断因数倍数", "找质数合数", "应用倍数特征"],
            "scope_note": "不扩展到最大公因数和最小公倍数的系统计算。",
        },
        {
            "unit": "第四单元：多边形的面积",
            "lessons": ["比较图形的面积", "认识底和高", "平行四边形的面积", "三角形的面积", "梯形的面积"],
            "points": ["底和高", "平行四边形面积", "三角形面积", "梯形面积", "转化思想"],
            "quiz_focus": ["公式理解", "代入计算", "单位意识", "简单应用题"],
            "scope_note": "只用五年级范围内的平面图形面积公式。",
        },
        {
            "unit": "第五单元：分数的意义",
            "lessons": ["分数的再认识", "分饼", "分数与除法", "分数基本性质", "找最大公因数", "约分"],
            "points": ["分数意义", "真分数假分数", "带分数", "分数与除法", "约分"],
            "quiz_focus": ["分数表示", "分数与除法互化", "约分基础"],
            "scope_note": "不提前进入复杂异分母分数运算。",
        },
        {
            "unit": "第六单元：组合图形的面积",
            "lessons": ["组合图形的面积", "成长的脚印", "公顷、平方千米"],
            "points": ["分割法", "添补法", "面积单位换算", "估算不规则图形面积"],
            "quiz_focus": ["选择分割方法", "简单组合面积计算", "单位换算"],
            "scope_note": "不设计过复杂竞赛型图形题。",
        },
        {
            "unit": "第七单元：可能性",
            "lessons": ["谁先走", "摸球游戏"],
            "points": ["可能性大小", "公平性", "随机现象", "简单推理"],
            "quiz_focus": ["判断公平", "比较可能性", "解释理由"],
            "scope_note": "只做直观概率，不引入概率公式化计算。",
        },
    ],
    "math_pep": [
        {
            "unit": "第一单元：小数乘法",
            "lessons": ["小数乘整数", "小数乘小数", "积的近似数", "整数乘法运算定律推广到小数"],
            "points": ["小数乘法意义", "积的小数位数", "近似数", "简便计算"],
            "quiz_focus": ["计算", "判断小数位数", "估算", "应用题"],
            "scope_note": "按五上小数乘法范围出题。",
        },
        {
            "unit": "第二单元：位置",
            "lessons": ["用数对表示位置"],
            "points": ["列与行", "数对", "位置变化"],
            "quiz_focus": ["读写数对", "根据数对定位"],
            "scope_note": "不扩展坐标系象限知识。",
        },
        {
            "unit": "第三单元：小数除法",
            "lessons": ["除数是整数的小数除法", "一个数除以小数", "商的近似数", "循环小数"],
            "points": ["小数除法", "商不变性质", "近似数", "循环小数"],
            "quiz_focus": ["计算", "验算", "解决问题"],
            "scope_note": "不超过五上计算难度。",
        },
        {
            "unit": "第四单元：可能性",
            "lessons": ["事件发生的确定性和不确定性", "可能性大小"],
            "points": ["一定", "可能", "不可能", "可能性大小"],
            "quiz_focus": ["判断可能性", "比较可能性"],
            "scope_note": "只做直观概率。",
        },
        {
            "unit": "第五单元：简易方程",
            "lessons": ["用字母表示数", "解简易方程", "实际问题与方程"],
            "points": ["字母表示数", "等式性质", "解方程", "列方程解决问题"],
            "quiz_focus": ["代入求值", "解一步/两步方程", "列方程"],
            "scope_note": "不提前进入初中方程组。",
        },
        {
            "unit": "第六单元：多边形的面积",
            "lessons": ["平行四边形面积", "三角形面积", "梯形面积", "组合图形面积"],
            "points": ["底高", "面积公式", "转化思想", "组合图形"],
            "quiz_focus": ["公式计算", "应用题", "单位"],
            "scope_note": "不设计竞赛型图形题。",
        },
    ],
    "english_fltrp": [
        {
            "unit": "Unit 1：My school is cool",
            "lessons": ["Ready to learn", "Story time", "Words and sentences", "Phonics", "Unit review"],
            "points": ["school places", "there is/there are", "school life", "feelings about school"],
            "quiz_focus": ["英汉互译", "there be 句型", "听读理解", "短句表达"],
            "scope_note": "围绕外研社刘兆义版五上 Unit 1，不扩展初中语法。",
        },
        {
            "unit": "Unit 2：School activities are fun!",
            "lessons": ["Story time", "Activities and festivals", "Words and sentences", "Phonics", "Unit review"],
            "points": ["school activities", "festival/activity words", "whose", "simple descriptions"],
            "quiz_focus": ["词义", "活动表达", "问答匹配", "短句表达"],
            "scope_note": "围绕校园活动和基础表达，不做复杂时态扩展。",
        },
        {
            "unit": "Unit 3：The ice world",
            "lessons": ["Story time", "Polar animals", "Nature words", "Phonics", "Unit review"],
            "points": ["polar animals", "north/middle/land/ocean", "fresh water", "environment words"],
            "quiz_focus": ["动物和自然词汇", "课文信息提取", "句子理解", "简单表达"],
            "scope_note": "只围绕课本里的冰雪世界和自然主题词。",
        },
        {
            "unit": "Unit 4：I love the sea!",
            "lessons": ["Story time", "Sea animals", "Ocean protection", "Poster task", "Unit review"],
            "points": ["sea animals", "dirty/plastic/rubbish", "poster", "choose sentences"],
            "quiz_focus": ["海洋词汇", "环保短句", "课文理解", "海报表达"],
            "scope_note": "围绕五上海洋主题，不扩展复杂环保议论文。",
        },
        {
            "unit": "Unit 5：Work it out!",
            "lessons": ["Story time", "Detective problem", "Diary/card", "Words and sentences", "Unit review"],
            "points": ["detective", "problem", "must", "answer/key", "diary/card"],
            "quiz_focus": ["词汇拼写", "问题解决表达", "must 用法", "课文理解"],
            "scope_note": "围绕课本故事和问题解决，不做复杂推理题。",
        },
        {
            "unit": "Unit 6：Big days",
            "lessons": ["Story time", "Festival words", "Past-time words", "Celebration", "Unit review"],
            "points": ["mooncake", "celebrate", "could", "ago", "lunar", "festival culture"],
            "quiz_focus": ["节日词汇", "基础过去表达", "中译英", "课文理解"],
            "scope_note": "围绕课本节日和故事，不扩展初中过去时系统语法。",
        },
    ],
    "english_pep": [
        {
            "unit": "Unit 1：What's he like?",
            "lessons": ["人物性格与外貌"],
            "points": ["old/young", "funny/kind/strict", "What's ... like?"],
            "quiz_focus": ["词义", "人物描述", "问答匹配"],
            "scope_note": "不要求复杂人物作文。",
        },
        {
            "unit": "Unit 2：My week",
            "lessons": ["星期与课程活动"],
            "points": ["days of week", "What do you have/do ...?"],
            "quiz_focus": ["星期词", "课程活动", "问答句"],
            "scope_note": "围绕一周活动表达。",
        },
        {
            "unit": "Unit 3：What would you like?",
            "lessons": ["食物与点餐"],
            "points": ["food/drink", "would like", "favourite"],
            "quiz_focus": ["词汇", "点餐问答", "喜好表达"],
            "scope_note": "不扩展复杂餐厅对话。",
        },
        {
            "unit": "Unit 4：What can you do?",
            "lessons": ["能力表达"],
            "points": ["can", "sing/dance/cook", "I can ..."],
            "quiz_focus": ["动词词汇", "can 句型", "自我表达"],
            "scope_note": "不扩展情态动词系统语法。",
        },
        {
            "unit": "Unit 5：There is a big bed",
            "lessons": ["房间物品与位置"],
            "points": ["there is/are", "room words", "prepositions"],
            "quiz_focus": ["方位词", "there be", "看图描述"],
            "scope_note": "只做基础空间表达。",
        },
        {
            "unit": "Unit 6：In a nature park",
            "lessons": ["自然公园"],
            "points": ["nature words", "Is there ...?", "Are there ...?"],
            "quiz_focus": ["自然词汇", "there be 问答", "描述公园"],
            "scope_note": "围绕教材单元主题。",
        },
    ],
}


def get_subject_units(subject: str, version: str | None = None) -> list[dict[str, Any]]:
    key = subject
    if subject == "math":
        key = "math_pep" if version and "人教" in version else "math_bsd"
    if subject == "english":
        key = "english_pep" if version and "人教" in version else "english_fltrp"
    return CURRICULUM.get(key, [])


def find_curriculum_context(subject: str, text: str, version: str | None = None) -> dict[str, Any] | None:
    normalized = text.lower().replace(" ", "")
    for unit in get_subject_units(subject, version):
        candidates = [unit["unit"], *unit.get("lessons", []), *unit.get("points", [])]
        if any(str(candidate).lower().replace(" ", "") in normalized for candidate in candidates):
            return unit
    return None
