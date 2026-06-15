"""상위 선곡 작곡가의 출생년도를 시드한다(시대 분포 차트용).

작곡가 이름은 백엔드 Composer.name 의 짧은 표기를 키로 한다. 시드는 부분 매칭
(icontains)로 적용되어 "바흐", "요한 제바스티안 바흐" 등 표기 차이를 흡수한다.
이미 birth_year 가 채워진 작곡가는 --force 없이는 건드리지 않는다.

용례:
    python manage.py seed_composer_birth_years
    python manage.py seed_composer_birth_years --force
"""

from django.core.management.base import BaseCommand

from apps.time_manage.models import Composer

# 짧은 한글 표기 → 출생년도. 클래식 선곡 빈도 상위권 위주로 큐레이션.
BIRTH_YEARS = {
    # 르네상스
    "팔레스트리나": 1525,
    "가브리엘리": 1557,
    "몬테베르디": 1567,
    # 바로크
    "비발디": 1678,
    "텔레만": 1681,
    "바흐": 1685,
    "헨델": 1685,
    "스카를라티": 1685,
    "퍼셀": 1659,
    "코렐리": 1653,
    "라모": 1683,
    "쿠프랭": 1668,
    "알비노니": 1671,
    "파헬벨": 1653,
    # 고전
    "하이든": 1732,
    "모차르트": 1756,
    "베토벤": 1770,  # 경계값 — era_override 로 낭만 처리
    "글루크": 1714,
    "보케리니": 1743,
    "살리에리": 1750,
    "클레멘티": 1752,
    # 낭만
    "슈베르트": 1797,
    "베를리오즈": 1803,
    "멘델스존": 1809,
    "쇼팽": 1810,
    "슈만": 1810,
    "리스트": 1811,
    "바그너": 1813,
    "베르디": 1813,
    "브루크너": 1824,
    "스메타나": 1824,
    "브람스": 1833,
    "보로딘": 1833,
    "생상스": 1835,
    "비제": 1838,
    "무소르그스키": 1839,
    "차이콥스키": 1840,
    "드보르자크": 1841,
    "드보르작": 1841,
    "그리그": 1843,
    "림스키코르사코프": 1844,
    "포레": 1845,
    "엘가": 1857,
    "파가니니": 1782,
    "로시니": 1792,
    "도니체티": 1797,
    "프랑크": 1822,
    # 후기낭만/근대 (1860–1909)
    "말러": 1860,
    "볼프": 1860,
    "드뷔시": 1862,
    "리하르트 슈트라우스": 1864,
    "슈트라우스": 1864,
    "시벨리우스": 1865,
    "닐센": 1865,
    "사티": 1866,
    "라흐마니노프": 1873,
    "라벨": 1875,
    "쇤베르크": 1874,
    "아이브스": 1874,
    "홀스트": 1874,
    "바르토크": 1881,
    "스트라빈스키": 1882,
    "코다이": 1882,
    "베베른": 1883,
    "베르크": 1885,
    "프로코피예프": 1891,
    "프로코피에프": 1891,
    "오네게르": 1892,
    "미요": 1892,
    "힌데미트": 1895,
    "거슈윈": 1898,
    "거슈인": 1898,
    "풀랑크": 1899,
    # 현대 (1910–)
    "바버": 1910,
    "쇼스타코비치": 1906,  # 1910 미만 → 근대로 분류됨
    "메시앙": 1908,
    "브리튼": 1913,
    "번스타인": 1918,
    "리게티": 1923,
    "불레즈": 1925,
    "베리오": 1925,
    "쿠르탁": 1926,
    "슈톡하우젠": 1928,
    "펜데레츠키": 1933,
    "라이히": 1936,
    "글래스": 1937,
    "페르트": 1935,
    "아르보 페르트": 1935,
    "윤이상": 1917,
}

# 출생년도 휴리스틱을 덮어쓸 작곡가(경계값 보정).
ERA_OVERRIDES = {
    "베토벤": "낭만",  # 1770 — 관례상 낭만으로 분류
}


class Command(BaseCommand):
    help = "상위 선곡 작곡가의 출생년도/시대 보정을 시드한다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="이미 birth_year 가 있는 작곡가도 덮어쓴다.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        updated = 0
        matched_names = set()

        for short_name, year in BIRTH_YEARS.items():
            override = ERA_OVERRIDES.get(short_name)
            composers = Composer.objects.filter(name__icontains=short_name)
            for composer in composers:
                changed = False
                if force or composer.birth_year is None:
                    composer.birth_year = year
                    changed = True
                if override and (force or not composer.era_override):
                    composer.era_override = override
                    changed = True
                if changed:
                    composer.save(update_fields=["birth_year", "era_override"])
                    updated += 1
                    matched_names.add(composer.name)

        total = Composer.objects.count()
        seeded = Composer.objects.exclude(birth_year__isnull=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"작곡가 {updated}명 업데이트. "
                f"전체 {total}명 중 {seeded}명 출생년도 보유."
            )
        )
