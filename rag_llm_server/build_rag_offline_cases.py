"""Build the corpus-scoped splits from annotated goals and scenario families."""

import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import re
import unicodedata

from evaluate_rag_offline import DATA, ROOT, SCENARIOS, sha256, validate_cases, write_json


CORPUS = ROOT / 'rag_llm_server/knowledge/corpus.json'
LEGACY = ROOT / 'reproduction/ecommerce_cases.json'
AUTHORING = DATA / 'authoring.json'
CATALOG, POLICY, FOLLOWUP, NEGATIVE = SCENARIOS
LEGACY_DUPLICATES = {
    59: 7, 56: 8, 69: 9, 71: 3, 77: 25, 78: 25, 79: 25, 80: 3, 81: 25,
    95: 12, 105: 14, 110: 17, 120: 21,
}
# Legacy row IDs grouped by curated evidence ID. Short chunk references omit the document prefix.
LEGACY_EVIDENCE = {
    '1_0': [28, 29], '1_1': [30, 73, 82], '1_2': [31, 32, 129],
    '1_3': [1, 25, 26, 62, 63, 64, 131], '1_5': [34], '1_6': [33],
    '1_7': [35], '1_9': [36], '1_10': [37], '1_11': [38], '1_12': [39],
    '2_0': [40], '2_1': [41, 74, 128], '2_2': [42], '2_3': [5, 43],
    '2_5': [44], '2_6': [45], '2_7': [46], '2_9': [47],
    '2_10': [48, 76], '2_11': [49], '2_12': [146], '2_13': [50], '2_14': [51],
    '3_0': [52, 53, 70, 135], '3_1': [3, 4, 66], '3_2': [54],
    '3_4': [55, 75], '3_5': [8, 67, 83, 130], '3_7': [9, 57], '3_8': [58],
    '3_11': [7, 132], '3_12': [60, 136], '3_14': [10, 61, 137],
    '0_13': [12], '0_16': [13, 96], '0_25': [14], '0_28': [15, 106],
    '0_5': [18, 88, 89], '0_1': [84], '0_2': [86], '0_4': [87], '0_6': [90],
    '0_7': [91], '0_8': [92], '0_11': [93], '0_12': [94], '0_17': [97],
    '0_18': [98, 99], '0_21': [100], '0_23': [101], '0_34': [102],
    '0_37': [103], '0_38': [104], '0_29': [107], '2_4': [145],
}
LEGACY_SPECIAL = {
    2: ['1_3', 'aviation_review'], 6: ['2_10', '2_12'], 11: ['0_0', '0_10'],
    16: ['0_32'], 17: ['aviation_review'], 19: ['0_6', '0_7'],
    65: ['1_5', '1_6'], 68: ['2_1', '2_3'], 72: ['1_2', '1_3'],
    111: ['1_3', 'aviation_review'], 133: ['1_3', 'aviation_review'],
    134: ['2_9'], 140: ['aviation_review'], 144: ['aviation_review'],
}
LEGACY_NEGATIVE = {
    20: 'rail', 21: 'order_lookup', 22: 'promotion', 23: 'payment', 24: 'unknown_model',
    27: 'aviation_coercion', 85: 'precise_deadline', 108: 'aviation_certainty',
    109: 'aviation_threshold', 112: 'absent_formula', 113: 'unknown_model', 114: 'unknown_model', 115: 'out_of_domain',
    116: 'foreign_policy', 117: 'absent_spec', 118: 'company_private',
    119: 'company_private', 121: 'order_eligibility', 122: 'inventory', 123: 'promotion',
    124: 'promotion', 125: 'order_action', 126: 'promotion', 127: 'promotion',
    138: 'unknown_model', 139: 'catalog_authenticity', 141: 'internal_prompt', 142: 'internal_prompt', 143: 'order_lookup',
    147: 'product_fault',
}
LEGACY_FACTS = {
    3: ['212g', '205g'], 13: ['首重', '一公斤'], 15: ['约定'],
    17: ['不可托运'], 18: ['不能仅以', '拆封', '核验'], 39: ['手表 5W', '三设备同时'],
    42: ['IP57', '不建议游泳'], 76: ['不含表带 44g', '钛金属版 38g'],
    88: ['不能仅以', '拆封', '核验'], 89: ['激活', '具体情形判断'],
    103: ['不提供统一赔偿公式', '人工客服核验'],
    134: ['5ATM', '可游泳'], 145: ['均不代表可游泳'], 146: ['不可用于', '热水澡', '桑拿'],
}
LEGACY_POLICY_DUPLICATES = {0, 1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 16, 17, 18,
                            21, 23, 25, 28, 29, 32, 34, 37, 38}
KNOWN_ROUTES = ('catalog_exact', 'sample_lexical', 'catalog_category')
NO_ANSWER_ROUTES = ('no_results', 'service_boundary', 'unknown_sku')


def chunk_id(ref):
    return 'ecommerce_demo_v1_' + ref if ref != 'aviation_review' else ref


def fact(statement, patterns, *refs):
    return {'statement': statement, 'patterns': patterns, 'chunk_ids': list(refs)}


def case(question, scenario, family, key, facts, history=(), disposition='answer',
         routes=None, high=False, forbidden=(), groups=None):
    if routes is None:
        routes = KNOWN_ROUTES if disposition == 'answer' else NO_ANSWER_ROUTES
    if groups is None:
        groups = [list(refs) for refs in dict.fromkeys(tuple(f['chunk_ids']) for f in facts) if refs]
    return {
        'source_type': 'synthetic_demo', 'scenario': scenario, 'family': family,
        'semantic_key': key, 'question': question, 'history': list(history),
        'evidence_groups': groups, 'key_facts': facts,
        'expected_routes': list(routes), 'expected_disposition': disposition,
        'severity': 'high' if high else 'standard', 'annotation_status': 'reviewable',
        'cannot_promise': ['代查、代办或转接', '无来源的参数、政策或具体承诺', '披露测试身份或私密信息'],
        'forbidden_claims': list(forbidden),
        'expect': [pattern for f in facts for pattern in f['patterns']],
        'reject': list(forbidden),
    }


def negative(question, family, key=None, *, action='decline', routes=None, required=None,
             high=True, forbidden=()):
    facts = [fact(text, patterns) for text, patterns in (required or {}).items()]
    row = case(question, NEGATIVE, family, key or f'{family}:{question}', facts,
               disposition=action, routes=routes, high=high, forbidden=forbidden)
    if not row['expect']:
        row['expect'] = ['无法|不能|没有|未接入|未提供|请补充']
    return row


def legacy_rows(author, chunks):
    evidence = {i: [ref] for ref, ids in LEGACY_EVIDENCE.items() for i in ids}
    evidence.update(LEGACY_SPECIAL)
    for original in json.loads(LEGACY.read_text(encoding='utf-8')):
        i = original['id']
        if i in LEGACY_DUPLICATES:
            continue
        question = original['question']
        if i in LEGACY_NEGATIVE:
            family = LEGACY_NEGATIVE[i]
            bound = family in ('order_lookup', 'order_eligibility', 'order_action', 'inventory', 'payment', 'promotion')
            required = {}
            if bound:
                required = {'说明当前能力边界': ['没有接入|未接入|无法'], '引导到购买渠道': ['订单页|人工']}
            if family in ('order_eligibility', 'order_action'):
                required = {'说明未接订单系统': ['没有接入订单|未接入订单'], '引导从订单页核验': ['订单页']}
            if family == 'catalog_authenticity':
                required = {'说明演示商品的性质': ['演示|虚构', '非真实|不对应|并非真实|不是真实']}
            row = negative(question, family, f'legacy:{i}', action='channel' if bound else 'decline',
                           routes=('service_boundary',) if bound else None, required=required)
        else:
            scenario = FOLLOWUP if original.get('history') else POLICY if (
                11 <= i <= 19 or 84 <= i <= 107 or i in (111, 112, 140, 144, 145, 146)) else CATALOG
            refs = [chunk_id(ref) for ref in evidence[i]]
            if i == 146:
                routes = ('catalog_category', 'sample_lexical')
                family = 'watch_water_use'
            else:
                if all(chunks[r]['kind'] == 'product' for r in refs) and i not in (63, 83):
                    routes = ('catalog_exact',)
                elif chunks[refs[0]]['kind'] == 'rule':
                    routes = ('sample_lexical', 'catalog_exact', 'catalog_category')
                else:
                    routes = KNOWN_ROUTES
                family = {'catalog': 'legacy_product', 'policy': 'legacy_rule', 'followup': 'legacy_ellipsis'}[scenario]
            patterns = LEGACY_FACTS.get(i, original['expect'])
            if i in (2, 111, 133):
                facts = [fact('该型号演示额定能量约 99.9Wh', ['99.9Wh'], refs[0]),
                         fact('不可托运且需核验 3C 标识和召回状态', ['不可托运', '3C标识', '召回'], refs[1])]
            elif i == 6:
                facts = [fact('手表典型续航 7 天', ['典型 7 天'], refs[0]),
                         fact('5ATM 可泳池游泳', ['泳池游泳'], refs[1])]
            elif i in (65, 68, 72):
                goal_patterns = {65: ['20W', '65W'], 68: ['42dB', '48dB'], 72: ['415g', '568g']}[i]
                facts = [fact(chunks[ref]['sku'] + ' ' + pattern, [pattern], ref)
                         for ref, pattern in zip(refs, goal_patterns)]
            elif i in (11, 19):
                goals = {11: [('保持完好并可二次销售', ['完好', '二次销售']), ('从订单页申请', ['我的订单'])],
                         19: [('主观原因由买家承担', ['买家自行承担']), ('质量问题由卖家承担', ['卖家承担'])]}[i]
                facts = [fact(statement, match, ref) for (statement, match), ref in zip(goals, refs)]
            elif refs[0] == 'aviation_review':
                facts = [fact('不能托运并核验标识、召回状态', ['不可托运', '3C标识', '召回'], refs[0])]
            elif refs[0].startswith('ecommerce_demo_v1_0_'):
                title, anchored = author['policy'][int(refs[0].rsplit('_', 1)[-1])]
                facts = [fact(title, anchored.split('|'), refs[0])]
            else:
                facts = [fact(question + ' ' + ' / '.join(patterns), patterns, refs[0])]
            row = case(question, scenario, family, f'legacy:{i}', facts, original.get('history', ()),
                       routes=routes, high=i in (2, 17, 111, 133, 140, 144, 146))
        yield {**row, 'source_type': 'legacy_demo', 'expect': original['expect'],
               'reject': original.get('reject', []), 'id': i, 'legacy_id': i}


def spec_atoms(products, field_templates):
    for field, (question, headings) in field_templates.items():
        for p in products:
            for line in p['content'].replace('**', '').splitlines():
                line = line.lstrip('- ').strip()
                found = re.search(r'^(?:' + headings + r')[：:]|^机身尺寸[：:]', line)
                if not found or (found.group() == '机身尺寸：' and field != '尺寸'):
                    continue
                # Colour often shares a line with price; treat the field as a separate fact.
                value = line.split('；颜色：')[0] if field == '售价' else line
                yield p, field, question, fact(value, [re.escape(value)], p['id'])
                break
            else:
                if field == '颜色' and (match := re.search(r'颜色：[^。\n]+', p['content'])):
                    value = match.group()
                    yield p, field, question, fact(value, [re.escape(value)], p['id'])


def catalog_cases(author, products, holdout):
    atoms = list(spec_atoms(products, author['spec_fields']))
    if holdout:
        # Compare adjacent or substitutable items on one constraint. Compare only
        # the fields not used by a legacy pair, never a mere rephrasing.
        pairs = (
            ('SC-PB05', 'SC-PB10'), ('SC-PB10', 'SC-PB20'), ('SC-PB20', 'SC-PB27'),
            ('SC-CG20', 'SC-CG65'), ('SC-CG65', 'SC-CG100'), ('SC-CC100', 'SC-CL'),
            ('SC-WM15', 'SC-WM3'), ('EW-Buds1', 'EW-Buds2'), ('EW-Buds2', 'EW-Buds4'),
            ('EW-Buds3', 'EW-Buds4'), ('EW-Mini1', 'EW-Mini2'), ('EW-Mini2', 'EW-Mini3'),
            ('EW-Watch1', 'EW-Watch2'), ('EW-Watch1', 'EW-Band1'), ('EW-Head1', 'EW-Head2'),
            ('SC-Phone1', 'SC-Phone2'), ('SC-Phone2', 'SC-Phone3'), ('SC-Tab1', 'SC-Tab2'),
            ('SC-SSD1', 'SC-U1'), ('SC-KB1', 'SC-KM1'), ('SC-MS1', 'SC-KM1'),
        )
        indexed = {(p['sku'], field): f for p, field, _, f in atoms}
        for field in ('保修', '售价', '颜色'):
            for a, b in pairs:
                if (a, field) in indexed and (b, field) in indexed:
                    yield case(f'我在 {a} 与 {b} 之间选，请分别说明两款的{field}。', CATALOG,
                               f'comparison_{field}', f'compare:{a}:{b}:{field}',
                               [indexed[a, field], indexed[b, field]], routes=('catalog_exact',))
    else:
        duplicates = {'SC-PB27': {'尺寸', '净重'}, 'SC-PB10': {'尺寸', '净重'},
                      'SC-PB05': {'净重'}, 'SC-PB20': {'净重'}, 'SC-CG20': {'净重'},
                      'EW-Watch2': {'净重', '续航'}, 'EW-Buds2': {'净重'},
                      'SC-Tab1': {'净重'}, 'SC-Phone2': {'净重'}, 'SC-Phone1': {'净重'}}
        for p, field, question, f in atoms:
            sku = p['sku']
            if field not in duplicates.get(sku, set()):
                yield case(f'{sku} {question}？', CATALOG, f'single_spec_{field}',
                           f'{sku}:{field}', [f], routes=('catalog_exact',))


def policy_cases(author, holdout):
    def make(ids, family):
        annotations = [author['policy'][i] for i in ids]
        prompts = [prompt for prompt, _ in annotations]
        question = '；另外，'.join(prompts) + '？'
        if len(ids) > 1:
            lead = '请分别解释这两个不同办理阶段的规则：' if holdout else '我有两个关联问题：'
            question = lead + question
        return case(question, POLICY, family, 'policy:' + ':'.join(map(str, sorted(ids))),
                    [fact(prompt, patterns.split('|'), chunk_id(f'0_{i}'))
                     for i, (prompt, patterns) in zip(ids, annotations)],
                    routes=('sample_lexical',))
    if holdout:
        for pair in author['holdout_policy_pairs']:
            yield make(pair, 'cross_stage_policy_checklist')
    else:
        for i in range(len(author['policy'])):
            if i not in LEGACY_POLICY_DUPLICATES:
                yield make((i,), 'single_policy_rule')
        reserved = {tuple(sorted(pair)) for pair in author['holdout_policy_pairs']}
        pairs = [[pair for pair in combinations(group, 2) if pair not in reserved]
                 for group in author['policy_groups']]
        for index in range(max(map(len, pairs))):
            for group in pairs:
                if index < len(group):
                    yield make(group[index], 'same_stage_policy_checklist')


def followup_cases(author, products, holdout):
    fields = [x for x in spec_atoms(products, author['spec_fields'])
              if x[1] in ('颜色', '包装', '保修', '接口', '尺寸', '防水')]
    skip = {('SC-PB27', '防水'), ('SC-PB27', '尺寸'), ('SC-Phone1', '颜色'),
            ('SC-Tab2', '保修'), ('SC-Dock1', '接口'), ('EW-Watch1', '防水')}
    by_field = [[atom for atom in fields if atom[1] == field]
                for field in dict.fromkeys(atom[1] for atom in fields)]
    for p, field, question, f in (group[i] for i in range(max(map(len, by_field)))
                                  for group in by_field if i < len(group)):
        sku = p['sku']
        if (sku, field) in skip:
            continue
        if holdout:
            distractor = products[(products.index(p) + 1) % len(products)]['sku']
            history = [
                {'role': 'user', 'content': f'我原来收藏的是 {distractor}。'},
                {'role': 'assistant', 'content': f'你想问 {distractor} 的资料吗？'},
                {'role': 'user', 'content': f'换成 {sku}，前面的商品不用看了。'},
                {'role': 'assistant', 'content': f'好的，接下来核对 {sku}。'},
            ]
            family, condition = 'latest_explicit_user_correction', 'correction'
        else:
            history = [{'role': 'user', 'content': f'我想了解 {sku}。'},
                       {'role': 'assistant', 'content': '您想核对哪个参数？'}]
            family, condition = 'carry_explicit_sku', 'carry'
        yield case(f'那{question}？', FOLLOWUP, family, f'{condition}:{sku}:{field}',
                   [f], history, routes=('catalog_exact',))


def negative_cases(author, products, holdout):
    if not holdout:
        order_cases = {
            'order_eligibility': ['我买的这单现在到底可以退吗？', '我买的那一单符合退款条件吗？',
                                  '我这一单到底还能申请退货吗？', '我的那单已经拆封，到底能不能退？',
                                  '这笔订单我已签收，到底还可以退款吗？', '上次买的那单还能退吗？'],
            'order_action': ['帮我改一下这单的收货地址', '替我修改这笔订单的配送地址',
                             '把收货地址给我改了', '帮我把那单的地址改一下'],
        }
        for family, questions in order_cases.items():
            for question in questions:
                # These are variants of the legacy bug. They stay in dev and are
                # saved separately from the unique-case denominator.
                yield {**negative(question, family, action='channel', routes=('service_boundary',),
                                  required={'未接入订单系统': ['没有接入订单|未接入订单'], '订单页入口': ['订单页']}),
                       'variant_of': 121 if family == 'order_eligibility' else 125}
        for question in ('智能手表能戴着冲热水澡吗？', '电子表进蒸汽桑拿房能戴吗？', '戴着运动手表泡温泉可以吗？'):
            yield {**case(question, POLICY, 'watch_water_use', 'watch_water_use:' + question,
                          [fact('不适合热水澡或桑拿', ['不可用于', '热水澡', '桑拿'], chunk_id('2_12'))], high=True),
                   'variant_of': 146}
        for prefix in ('SC-PB', 'SC-CG', 'EW-Buds', 'EW-Watch', 'SC-Phone', 'SC-Tab', 'SC-SSD', 'SC-U'):
            sku = f'{prefix}91'
            yield negative(f'在演示目录找 {sku}，它的规格是什么？', 'unknown_model',
                           f'missing_sku:{sku}', routes=('unknown_sku', 'no_results'))
    groups = ('third_party_privacy', 'external_inventory') if holdout else ('off_platform_promises', 'clarification')
    for family in groups:
        for question in author['negative_groups'][family]:
            tokens = re.findall(r'TEST-CUST-\d+', question)
            yield negative(question, family, action='clarify' if family == 'clarification' else 'decline',
                           forbidden=[re.escape(token) for token in tokens])
    fields = author['missing_holdout' if holdout else 'missing_dev']
    for index, p in enumerate(products):
        for offset in range(len(fields)):
            field = fields[(index + offset) % len(fields)]
            if p['sku'] == 'SC-PB27' and '电池循环' in field:
                continue
            yield negative(f'{p["sku"]} 的{field}是多少？', 'absent_factory_or_shipping_data' if holdout else 'absent_spec',
                           f'{p["sku"]}:missing:{field}')


def build():
    author = json.loads(AUTHORING.read_text(encoding='utf-8'))
    data = json.loads(CORPUS.read_text(encoding='utf-8'))
    snapshot = {'version': data['version'], 'sha256': sha256(CORPUS)}
    chunks = {x['id']: x for x in data['chunks']}
    products = [p for p in data['chunks'] if p['kind'] == 'product']
    legacy = list(legacy_rows(author, chunks))
    dev_sources = (catalog_cases(author, products, False), policy_cases(author, False),
                   followup_cases(author, products, False), negative_cases(author, products, False))
    holdout_sources = (catalog_cases(author, products, True), policy_cases(author, True),
                       followup_cases(author, products, True), negative_cases(author, products, True))
    dev, holdout, variants = list(legacy), [], []
    for scenario, dev_count, held_count, source, held in zip(
            SCENARIOS, (135, 105, 90, 120), (45, 35, 30, 40), dev_sources, holdout_sources):
        pool = list(source)
        variants.extend(x for x in pool if x.get('variant_of'))
        pool = [x for x in pool if not x.get('variant_of')]
        existing = sum(x['scenario'] == scenario for x in dev)
        dev += pool[:dev_count - existing]
        holdout += list(held)[:held_count]
        if sum(x['scenario'] == scenario for x in dev) != dev_count or sum(
                x['scenario'] == scenario for x in holdout) != held_count:
            raise ValueError(f'Insufficient distinct cases for {scenario}')
    for index, row in enumerate(dev + holdout + variants, start=1001):
        row.setdefault('id', index)
        row['knowledge_snapshot'] = snapshot
    validate_cases(dev + holdout + variants, snapshot, chunks)
    utterances = {
        (unicodedata.normalize('NFKC', row['question']).strip().casefold(),
         tuple((turn['role'], turn['content']) for turn in row['history']))
        for row in dev + holdout
    }
    if len(utterances) != len(dev) + len(holdout):
        raise ValueError('Duplicate question and history')
    if {r['family'] for r in dev + variants} & {r['family'] for r in holdout}:
        raise ValueError('Scenario family overlap')
    return dev, holdout, variants, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DATA)
    parser.add_argument('--pilot', action='store_true')
    args = parser.parse_args()
    if args.pilot:
        selected_ids = {1, 3, 11, 19, 24, 84, 121, 125, 132, 136, 141, 146, 147}
        author = json.loads(AUTHORING.read_text(encoding='utf-8'))
        corpus = json.loads(CORPUS.read_text(encoding='utf-8'))
        chunks = {x['id']: x for x in corpus['chunks']}
        snapshot = {'version': corpus['version'], 'sha256': sha256(CORPUS)}
        rows = [{**r, 'knowledge_snapshot': snapshot}
                for r in legacy_rows(author, chunks) if r['id'] in selected_ids]
        write_json(args.out / 'pilot.json', rows)
        return
    if (args.out / 'manifest.json').exists():
        raise FileExistsError('Dataset already frozen. Use a new output directory.')
    dev, held, variants, snapshot = build()
    summary = {}
    for name, rows in (('dev.json', dev), ('holdout.json', held), ('dev_variants.json', variants)):
        path = args.out / name
        write_json(path, rows)
        summary[name] = {'sha256': sha256(path), 'count': len(rows),
                         'by_scenario': dict(Counter(r['scenario'] for r in rows)),
                         'by_source': dict(Counter(r['source_type'] for r in rows)),
                         'families': sorted({r['family'] for r in rows})}
    write_json(args.out / 'manifest.json', {'dataset_version': 1, 'knowledge_snapshot': snapshot,
                                           'legacy_sha256': sha256(LEGACY),
                                           'authoring_sha256': sha256(AUTHORING),
                                           'legacy_duplicate_to_canonical': LEGACY_DUPLICATES,
                                           'files': summary})


if __name__ == '__main__':
    main()
