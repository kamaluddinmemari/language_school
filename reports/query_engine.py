"""
موتور اجرای کوئری گزارش‌ساز دلخواه — همیشه فقط از روی whitelist فیلدهای هر DataSource کار
می‌کند (هیچ ورودی خام کاربر مستقیماً به ORM/SQL نمی‌رود)، پس امن است.
"""
from django.db.models import Sum, Avg, Count, Min, Max, Q
from datetime import date, datetime

from .registry_custom import SOURCES

AGG_FUNCS = {'sum': Sum, 'avg': Avg, 'count': Count, 'min': Min, 'max': Max}
FILTER_OPS = {'eq': '', 'gt': '__gt', 'gte': '__gte', 'lt': '__lt', 'lte': '__lte', 'contains': '__icontains'}


class ReportQueryError(Exception):
    pass


def _cast_value(raw, field_type):
    if raw is None or raw == '':
        return None
    if field_type == 'number':
        try:
            return float(raw) if '.' in str(raw) else int(raw)
        except (TypeError, ValueError):
            raise ReportQueryError(f'مقدار عددی نامعتبر: {raw}')
    if field_type in ('date', 'datetime'):
        try:
            return datetime.fromisoformat(str(raw)).date() if field_type == 'date' else datetime.fromisoformat(str(raw))
        except ValueError:
            raise ReportQueryError(f'مقدار تاریخ نامعتبر: {raw}')
    return raw


def _resolve_attr(obj, path):
    """مسیر نقطه‌چین (student__first_name) یا اسم یک property را روی یک instance مدل می‌خواند"""
    cur = obj
    for part in path.split('__'):
        if cur is None:
            return None
        cur = getattr(cur, part, None)
    return cur


def apply_filters(qs, source, filters):
    for f in (filters or []):
        fkey, op, value = f.get('field'), f.get('op', 'eq'), f.get('value')
        sf = source.field_map.get(fkey)
        if not sf or not sf.is_db_field or value in (None, ''):
            continue
        casted = _cast_value(value, sf.type)
        if op == 'neq':
            qs = qs.exclude(**{sf.db_field: casted})
        elif op == 'in':
            vals = value if isinstance(value, list) else [x.strip() for x in str(value).split(',') if x.strip()]
            qs = qs.filter(**{f"{sf.db_field}__in": vals})
        else:
            suffix = FILTER_OPS.get(op, '')
            qs = qs.filter(**{f"{sf.db_field}{suffix}": casted})
    return qs


def run_query(source_key, fields, filters=None, group_by=None, aggregations=None, start=None, end=None, limit=2000):
    source = SOURCES.get(source_key)
    if not source:
        raise ReportQueryError('منبع داده نامعتبر است')

    fields = [f for f in (fields or []) if f in source.field_map]
    group_by = [f for f in (group_by or []) if f in source.field_map and source.field_map[f].is_db_field]
    aggregations = [
        a for a in (aggregations or [])
        if a.get('field') in source.field_map and a.get('func') in AGG_FUNCS
        and (source.field_map[a['field']].is_db_field or a.get('func') == 'count')
    ]

    qs = source.base_qs()

    if source.date_field and (start or end):
        if start:
            qs = qs.filter(**{f"{source.date_field}__gte": start})
        if end:
            qs = qs.filter(**{f"{source.date_field}__lte": end})

    qs = apply_filters(qs, source, filters)

    if group_by:
        group_db_fields = [source.field_map[g].db_field for g in group_by]
        annotate_kwargs = {}
        agg_aliases = []  # (alias, header, fkey_or_none, func)
        for a in aggregations:
            fkey, func = a['field'], a['func']
            alias = f"{fkey}__{func}"
            agg_cls = AGG_FUNCS[func]
            db_field = source.field_map[fkey].db_field if func != 'count' else (source.field_map[fkey].db_field or 'id')
            annotate_kwargs[alias] = agg_cls(db_field)
            agg_aliases.append((alias, f"{source.field_map[fkey].label} ({func})"))
        if not annotate_kwargs:
            annotate_kwargs['__count'] = Count('id')
            agg_aliases.append(('__count', 'تعداد'))

        qs2 = qs.values(*group_db_fields).annotate(**annotate_kwargs).order_by()[:limit]
        rows = []
        for record in qs2:
            row = {}
            for gkey, db_field in zip(group_by, group_db_fields):
                val = record.get(db_field)
                sf = source.field_map[gkey]
                if sf.type == 'choice' and sf.choices:
                    val = sf.choices.get(str(val), val)
                row[gkey] = val
            for alias, header in agg_aliases:
                row[alias] = record.get(alias)
            rows.append(row)

        columns = [{'key': g, 'header': source.field_map[g].label} for g in group_by]
        columns += [{'key': alias, 'header': header} for alias, header in agg_aliases]
        return rows, columns

    # حالت تخت (بدون گروه‌بندی) — می‌تواند فیلدهای محاسباتی (property) هم داشته باشد
    objs = list(qs[:limit])
    rows = []
    for o in objs:
        row = {}
        for fkey in fields:
            sf = source.field_map[fkey]
            val = _resolve_attr(o, sf.db_field)
            if sf.type == 'choice' and sf.choices:
                val = sf.choices.get(str(val), val)
            elif hasattr(val, 'isoformat'):
                val = val.isoformat()
            row[fkey] = val
        rows.append(row)

    columns = [{'key': f, 'header': source.field_map[f].label} for f in fields]
    return rows, columns
