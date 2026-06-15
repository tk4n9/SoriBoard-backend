"""통계 페이지용 집계 API.

play history = TimeMusic ⨝ TimeInfo. 모든 엔드포인트는 공통 필터(`build_timemusic_filter`)
로 TimeMusic 쿼리셋을 만든 뒤 집계한다. 공통 응답 봉투:

    {
        "filters": {...},          # 적용된 필터(디버깅/표시용)
        "total_plays": <int>,      # 필터 적용 후 전체 선곡 수
        "labels": [...],           # 차트 x축/범례 라벨
        "values": [...],           # labels 와 1:1 대응하는 수치
        "items":  [{id, name, count}, ...]  # drill-down 용 식별자 포함
    }
"""

import datetime

from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncMonth, TruncWeek
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Composer, Semester, TimeMusic

# ---------------------------------------------------------------------------
# 시대 구분 (작곡가 출생년도 기준 휴리스틱 + era_override 수동 보정)
# ---------------------------------------------------------------------------
# (라벨, 상한) — birth_year < 상한 이면 해당 시대. 위에서부터 처음 매칭되는 구간.
ERA_BUCKETS = [
    ("르네상스", 1600),
    ("바로크", 1710),
    ("고전", 1770),
    ("낭만", 1860),
    ("후기낭만/근대", 1910),
    ("현대", None),  # 1910 이상
]
ERA_ORDER = [label for label, _ in ERA_BUCKETS] + ["미상"]


def era_for(birth_year, override=None):
    """출생년도(+보정)를 시대 라벨로 변환."""
    if override:
        return override
    if birth_year is None:
        return "미상"
    for label, upper in ERA_BUCKETS:
        if upper is None or birth_year < upper:
            return label
    return "미상"


# ---------------------------------------------------------------------------
# 공통 필터
# ---------------------------------------------------------------------------
def _semester_date_range(semester_id):
    """학기 id → (start_date, end_date).

    Semester 모델에 학기 시작/종료 날짜가 없어 관례적으로 매핑한다.
    1학기 = 해당 연도 3/1 ~ 8/31, 2학기 = 해당 연도 9/1 ~ 다음 연도 2/말일.
    (근사치이며, 정확한 학기 경계가 필요하면 Semester 에 날짜 필드 추가 필요.)
    """
    try:
        semester = Semester.objects.get(id=semester_id)
    except Semester.DoesNotExist:
        return None, None
    if semester.semester_num == 1:
        return (
            datetime.date(semester.year, 3, 1),
            datetime.date(semester.year, 8, 31),
        )
    return (
        datetime.date(semester.year, 9, 1),
        datetime.date(semester.year + 1, 2, 28),
    )


def build_timemusic_filter(params):
    """쿼리 파라미터를 TimeMusic 필터(Q 객체)로 변환.

    지원 파라미터: start, end (YYYY-MM-DD), semester_id, user_id, include_mentees.
    적용된 필터 정보를 함께 돌려준다(응답 봉투의 filters 필드).
    """
    q = Q()
    applied = {"scope": "all"}

    start = params.get("start")
    end = params.get("end")
    semester_id = params.get("semester_id")

    if semester_id:
        s_start, s_end = _semester_date_range(semester_id)
        if s_start:
            q &= Q(time__date__gte=s_start, time__date__lte=s_end)
            applied["semester_id"] = semester_id
            applied["start"] = str(s_start)
            applied["end"] = str(s_end)
    else:
        if start:
            q &= Q(time__date__gte=start)
            applied["start"] = start
        if end:
            q &= Q(time__date__lte=end)
            applied["end"] = end

    user_id = params.get("user_id")
    if user_id:
        include_mentees = str(params.get("include_mentees", "")).lower() in (
            "1",
            "true",
            "yes",
        )
        if include_mentees:
            q &= Q(time__users__id=user_id) | Q(time__mentees__id=user_id)
        else:
            q &= Q(time__users__id=user_id)
        applied["scope"] = "individual"
        applied["user_id"] = int(user_id)
        applied["include_mentees"] = include_mentees

    return q, applied


def base_queryset(request):
    """필터가 적용된 TimeMusic 쿼리셋과 filters 정보를 반환.

    M2M(time__users) 조인 시 중복 행이 생길 수 있어 distinct() 적용.
    """
    q, applied = build_timemusic_filter(request.query_params)
    qs = TimeMusic.objects.filter(q).distinct()
    return qs, applied


def _limit(request, default=15):
    try:
        return max(1, min(100, int(request.query_params.get("limit", default))))
    except (TypeError, ValueError):
        return default


def _top_by(qs, group_field, name_field, limit, id_field=None):
    """공통 top-N 집계. labels/values/items 봉투 부분을 만든다."""
    id_field = id_field or group_field
    rows = (
        qs.values(id_field, name_field)
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    labels, values, items = [], [], []
    for row in rows:
        name = row[name_field]
        labels.append(name)
        values.append(row["count"])
        items.append({"id": row[id_field], "name": name, "count": row["count"]})
    return labels, values, items


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
class StatsSummaryView(APIView):
    """헤더 KPI 카드용 요약 수치."""

    def get(self, request):
        qs, applied = base_queryset(request)
        agg = qs.aggregate(
            total_plays=Count("id"),
            composers=Count("music__composer", distinct=True),
            works=Count("music", distinct=True),
            conductors=Count("conductor", distinct=True),
            orchestras=Count("orchestra", distinct=True),
        )
        dates = qs.aggregate(first=Min("time__date"), last=Max("time__date"))
        return Response(
            {
                "filters": applied,
                "total_plays": agg["total_plays"],
                "composers": agg["composers"],
                "works": agg["works"],
                "conductors": agg["conductors"],
                "orchestras": agg["orchestras"],
                "date_start": str(dates["first"]) if dates["first"] else None,
                "date_end": str(dates["last"]) if dates["last"] else None,
            }
        )


class TopComposersStatsView(APIView):
    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()
        labels, values, items = _top_by(
            qs.exclude(music__composer__isnull=True),
            "music__composer__id",
            "music__composer__name",
            _limit(request),
        )
        return Response(
            {
                "filters": applied,
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": items,
            }
        )


class TopWorksStatsView(APIView):
    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()
        limit = _limit(request)
        rows = (
            qs.exclude(music__isnull=True)
            .values("music__id", "music__title", "music__composer__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )
        labels, values, items = [], [], []
        for row in rows:
            composer = row["music__composer__name"] or ""
            title = row["music__title"]
            label = f"{composer} - {title}" if composer else title
            labels.append(label)
            values.append(row["count"])
            items.append({"id": row["music__id"], "name": label, "count": row["count"]})
        return Response(
            {
                "filters": applied,
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": items,
            }
        )


class TopConductorsStatsView(APIView):
    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()
        labels, values, items = _top_by(
            qs.exclude(conductor__isnull=True),
            "conductor__id",
            "conductor__name",
            _limit(request),
        )
        return Response(
            {
                "filters": applied,
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": items,
            }
        )


class TopOrchestrasStatsView(APIView):
    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()
        labels, values, items = _top_by(
            qs.exclude(orchestra__isnull=True),
            "orchestra__id",
            "orchestra__name",
            _limit(request),
        )
        return Response(
            {
                "filters": applied,
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": items,
            }
        )


class PlaysOverTimeStatsView(APIView):
    """기간별 선곡 추이. ?bucket=week|month|semester (기본 month)."""

    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()
        bucket = request.query_params.get("bucket", "month")

        if bucket == "week":
            trunc = TruncWeek("time__date")
        else:
            trunc = TruncMonth("time__date")

        rows = (
            qs.annotate(period=trunc)
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        )

        if bucket == "semester":
            # month 결과를 학기 버킷(YYYY-N)으로 접는다.
            buckets = {}
            for row in rows:
                period = row["period"]
                if period is None:
                    continue
                sem = 1 if 3 <= period.month <= 8 else 2
                year = period.year if period.month >= 3 else period.year - 1
                key = f"{year}-{sem}"
                buckets[key] = buckets.get(key, 0) + row["count"]
            labels = sorted(buckets.keys())
            values = [buckets[k] for k in labels]
        else:
            labels, values = [], []
            for row in rows:
                period = row["period"]
                if period is None:
                    continue
                labels.append(
                    period.strftime("%Y-%m-%d" if bucket == "week" else "%Y-%m")
                )
                values.append(row["count"])

        return Response(
            {
                "filters": {**applied, "bucket": bucket},
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": [],
            }
        )


class EraDistributionStatsView(APIView):
    """시대(르네상스/바로크/...) 분포. 작곡가 출생년도 휴리스틱 사용."""

    def get(self, request):
        qs, applied = base_queryset(request)
        total = qs.count()

        rows = (
            qs.exclude(music__composer__isnull=True)
            .values(
                "music__composer__birth_year",
                "music__composer__era_override",
            )
            .annotate(count=Count("id"))
        )

        buckets = {label: 0 for label in ERA_ORDER}
        for row in rows:
            era = era_for(
                row["music__composer__birth_year"],
                row["music__composer__era_override"],
            )
            buckets[era] = buckets.get(era, 0) + row["count"]

        labels, values, items = [], [], []
        for label in ERA_ORDER:
            count = buckets.get(label, 0)
            if count == 0:
                continue
            labels.append(label)
            values.append(count)
            items.append({"id": label, "name": label, "count": count})

        unknown = buckets.get("미상", 0)
        unknown_share = round(unknown / total, 4) if total else 0

        return Response(
            {
                "filters": applied,
                "total_plays": total,
                "labels": labels,
                "values": values,
                "items": items,
                "unknown_share": unknown_share,
            }
        )
