"""Small, explicit service boundaries and history-aware retrieval queries."""
import re
import unicodedata


def normalize(text):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', text).lower())


def retrieval_query(messages):
    question = messages[-1]['content']
    # Carry only the preceding user's question, never an assistant's invented SKU.
    if re.match(r'^(那|它|这个|这款|刚才|上面|还有|能不能|可以吗|多重|多少钱|保修多久)', question):
        prior = [x['content'] for x in messages[:-1] if x['role'] == 'user']
        if prior:
            return '；'.join(x[:300] for x in prior[-2:]) + '；追问：' + question
    return question


def direct_answer(question):
    query = normalize(question)
    if query in ('你好', '您好', '嗨', '哈喽', 'hello'):
        return '您好，我是星核数码演示店的购物助手，可以介绍演示商品参数和购物售后规则。'
    if query in ('谢谢', '好的谢谢', '谢谢你', '再见'):
        return '不客气，欢迎继续咨询。'
    if any(x in query for x in ('高铁', '铁路', '火车')):
        return '当前演示知识库没有收录铁路携带规则，不能用航空规则推断。请查询铁路12306或车站的最新规定，并核实实物容量与标识。'
    if any(x in query for x in ('转人工', '人工客服', '投诉你', '我要投诉', '砍价', '便宜点', '优惠券', '打到我银行卡')):
        return '这项需求需要人工处理。演示系统尚未接入人工坐席或支付系统，请通过购买平台的订单页联系商家人工客服；我无法实际转接、发券或办理退款。'
    if any(x in query for x in ('我的订单', '我的退款', '订单号', '查一下订单', '查订单', '查物流', '到哪了', '实时库存', '还有货吗', '帮我退款', '帮我退货')):
        return '我没有接入订单、库存或支付系统，无法查询实时状态或代办操作。请打开购买平台的订单页查看，或联系商家人工客服；请勿在这里提供银行卡等敏感信息。'
    return ''
