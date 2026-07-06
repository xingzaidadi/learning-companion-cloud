from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeItem:
    subject: str
    unit: str
    lesson: str
    section: str
    knowledge_point: str
    skill: str
    difficulty: str = "basic"
    exam_weight: str = "medium"
    must_master: bool = True
    sample: str = ""


CHINESE_UNITS: list[dict[str, Any]] = [
    {
        "unit": "第一单元：万物有灵",
        "lessons": ["白鹭", "落花生", "桂花雨", "珍珠鸟"],
        "points": ["借物抒情", "关键句理解", "生字听写", "词语解释", "仿写表达"],
        "dictation": ["精巧", "适宜", "色素", "身段", "播种", "吩咐", "爱慕", "沉浸", "信赖"],
    },
    {
        "unit": "第二单元：提高阅读速度",
        "lessons": ["搭石", "将相和", "什么比猎豹的速度更快", "冀中的地道战"],
        "points": ["限时阅读", "提取信息", "概括事件", "关键词句", "说明方法"],
        "dictation": ["汛期", "平衡", "协调", "允诺", "胆怯", "冠军", "俯冲", "地道"],
    },
    {
        "unit": "第三单元：民间故事",
        "lessons": ["猎人海力布", "牛郎织女（一）", "牛郎织女（二）"],
        "points": ["复述故事", "缩写故事", "人物品质", "起因经过结果"],
        "dictation": ["酬谢", "叮嘱", "崩塌", "发誓", "稀罕", "妻子", "筛子"],
    },
    {
        "unit": "第四单元：家国情怀",
        "lessons": ["古诗三首", "少年中国说", "圆明园的毁灭", "小岛"],
        "points": ["资料辅助理解", "情感体会", "朗读背诵", "读后感表达"],
        "dictation": ["祭祀", "乃翁", "熏陶", "潜龙", "试翼", "毁灭", "辉煌"],
    },
    {
        "unit": "第五单元：说明文",
        "lessons": ["太阳", "松鼠"],
        "points": ["列数字", "作比较", "打比方", "抓特点", "说明顺序"],
        "dictation": ["摄氏度", "繁殖", "粮食", "煤炭", "乖巧", "清秀", "玲珑"],
    },
    {
        "unit": "第六单元：父母之爱",
        "lessons": ["慈母情深", "父爱之舟", "精彩极了和糟糕透了"],
        "points": ["场景描写", "细节描写", "情感变化", "联系生活表达"],
        "dictation": ["辞退", "压抑", "忙碌", "脊背", "启迪", "誊写", "谨慎"],
    },
    {
        "unit": "第七单元：四时景物",
        "lessons": ["古诗词三首", "四季之美", "鸟的天堂", "月迹"],
        "points": ["动态描写", "静态描写", "景物顺序", "画面想象", "优美语句积累"],
        "dictation": ["黎明", "红晕", "漆黑", "萤火虫", "榕树", "纠正", "嫉妒"],
    },
    {
        "unit": "第八单元：读书明智",
        "lessons": ["古人谈读书", "忆读书", "我的长生果"],
        "points": ["观点概括", "读书方法", "联系实际", "推荐理由", "日积月累"],
        "dictation": ["羞耻", "教诲", "谓之", "津津有味", "烦琐", "刊物", "馈赠"],
    },
]


MATH_UNITS: list[dict[str, Any]] = [
    {
        "unit": "第一单元：小数乘法",
        "points": ["小数乘整数", "小数乘小数", "积的近似数", "运算定律推广", "小数乘法应用题"],
        "examples": ["3.6×4=14.4", "2.4×0.3=0.72", "1.25×8=10"],
        "errors": ["小数点位置错误", "近似数保留位数错误", "应用题单位遗漏"],
    },
    {
        "unit": "第二单元：位置",
        "points": ["用数对表示位置", "根据数对确定位置", "列和行的顺序"],
        "examples": ["数对（3，4）表示第3列第4行"],
        "errors": ["列行顺序写反", "括号和逗号格式错误"],
    },
    {
        "unit": "第三单元：小数除法",
        "points": ["除数是整数的小数除法", "除数是小数的除法", "商的近似数", "循环小数", "小数除法应用题"],
        "examples": ["7.2÷3=2.4", "9.6÷0.3=32", "5.4÷6=0.9"],
        "errors": ["被除数和除数小数点移动不一致", "商的小数点未对齐", "余数处理错误"],
    },
    {
        "unit": "第四单元：可能性",
        "points": ["确定事件", "不确定事件", "可能性大小比较", "公平性判断"],
        "examples": ["袋中红球多，摸到红球可能性大"],
        "errors": ["把可能性大小说成一定发生", "没有根据数量比较"],
    },
    {
        "unit": "第五单元：简易方程",
        "points": ["用字母表示数", "等式的性质", "解简易方程", "列方程解决问题"],
        "examples": ["x+3=8，x=5", "3x=12，x=4"],
        "errors": ["等式两边未同时变化", "未知数关系找错"],
    },
    {
        "unit": "第六单元：多边形面积",
        "points": ["平行四边形面积", "三角形面积", "梯形面积", "组合图形面积"],
        "examples": ["平行四边形面积=底×高", "三角形面积=底×高÷2", "梯形面积=（上底+下底）×高÷2"],
        "errors": ["三角形忘记除以2", "高和斜边混淆", "单位平方遗漏"],
    },
    {
        "unit": "第七单元：数学广角",
        "points": ["植树问题两端都栽", "两端不栽", "一端栽", "封闭图形植树"],
        "examples": ["两端都栽：棵数=间隔数+1"],
        "errors": ["间隔数和棵数混淆", "没有判断是否封闭"],
    },
]


ENGLISH_UNITS: list[dict[str, Any]] = [
    {
        "unit": "Unit 1 My school is cool",
        "words": [("school", "学校"), ("library", "图书馆"), ("classroom", "教室"), ("teacher", "老师"), ("playground", "操场")],
        "sentences": ["This is our school.", "There is a library.", "My school is cool."],
        "skills": ["单词默写", "中英互译", "There is 句型", "学校场景阅读"],
    },
    {
        "unit": "Unit 2 School activities are fun",
        "words": [("draw", "画"), ("sing", "唱歌"), ("dance", "跳舞"), ("read", "阅读"), ("activity", "活动")],
        "sentences": ["We can sing and dance.", "School activities are fun."],
        "skills": ["动词认读", "can 句型", "活动表达"],
    },
    {
        "unit": "Unit 3 The ice world",
        "words": [("ice", "冰"), ("snow", "雪"), ("cold", "寒冷的"), ("world", "世界"), ("winter", "冬天")],
        "sentences": ["The ice world is cold.", "I can see snow."],
        "skills": ["自然场景词", "形容词使用", "阅读理解"],
    },
    {
        "unit": "Unit 4 I love the sea",
        "words": [("sea", "大海"), ("fish", "鱼"), ("boat", "船"), ("beach", "海滩"), ("love", "喜爱")],
        "sentences": ["I love the sea.", "There are fish in the sea."],
        "skills": ["场景词汇", "There are 句型", "表达喜好"],
    },
    {
        "unit": "Unit 5 Work it out",
        "words": [("work", "工作/解决"), ("problem", "问题"), ("think", "思考"), ("answer", "答案"), ("try", "尝试")],
        "sentences": ["Let's work it out.", "Try again."],
        "skills": ["解决问题表达", "祈使句", "短句造句"],
    },
    {
        "unit": "Unit 6 Big days",
        "words": [("birthday", "生日"), ("holiday", "假日"), ("party", "聚会"), ("gift", "礼物"), ("happy", "高兴的")],
        "sentences": ["Happy birthday!", "It is a big day."],
        "skills": ["节日词汇", "祝福语", "情景表达"],
    },
]


def iter_core_knowledge() -> list[KnowledgeItem]:
    items: list[KnowledgeItem] = []
    for unit in CHINESE_UNITS:
        for lesson in unit["lessons"]:
            for point in unit["points"]:
                items.append(KnowledgeItem("语文", unit["unit"], lesson, "课文理解", point, "课文理解", "core", "high", True))
        for word in unit["dictation"]:
            lesson = unit["lessons"][0]
            items.append(KnowledgeItem("语文", unit["unit"], lesson, "生字词", word, "生字听写", "basic", "high", True, f"听写词：{word}"))
    for unit in MATH_UNITS:
        for point in unit["points"]:
            items.append(KnowledgeItem("数学", unit["unit"], unit["unit"], "概念例题", point, "概念理解", "core", "high", True))
        for example in unit["examples"]:
            items.append(KnowledgeItem("数学", unit["unit"], unit["unit"], "例题", example, "计算准确", "basic", "high", True))
        for error in unit["errors"]:
            items.append(KnowledgeItem("数学", unit["unit"], unit["unit"], "易错点", error, "易错辨析", "core", "high", True))
    for unit in ENGLISH_UNITS:
        for word, meaning in unit["words"]:
            items.append(KnowledgeItem("英语", unit["unit"], unit["unit"], "单词表", word, "单词拼写", "basic", "high", True, f"{word}={meaning}"))
            items.append(KnowledgeItem("英语", unit["unit"], unit["unit"], "中英互译", meaning, "词义匹配", "basic", "high", True, f"{meaning}={word}"))
        for sentence in unit["sentences"]:
            items.append(KnowledgeItem("英语", unit["unit"], unit["unit"], "句型", sentence, "句型替换", "core", "high", True))
        for skill in unit["skills"]:
            items.append(KnowledgeItem("英语", unit["unit"], unit["unit"], "能力点", skill, "课文理解", "core", "medium", True))
    return items


def render_subject_material(subject: str) -> str:
    lines = [f"五年级上册{subject}结构化知识库", ""]
    for item in iter_core_knowledge():
        if item.subject != subject:
            continue
        sample = f"；样例：{item.sample}" if item.sample else ""
        lines.append(
            f"单元：{item.unit}\n课/节：{item.lesson}\n板块：{item.section}\n知识点：{item.knowledge_point}\n能力：{item.skill}\n难度：{item.difficulty}\n权重：{item.exam_weight}{sample}\n"
        )
    return "\n".join(lines)


def coverage_summary() -> dict[str, Any]:
    items = iter_core_knowledge()
    by_subject: dict[str, int] = {}
    for item in items:
        by_subject[item.subject] = by_subject.get(item.subject, 0) + 1
    return {"total": len(items), "by_subject": by_subject}
