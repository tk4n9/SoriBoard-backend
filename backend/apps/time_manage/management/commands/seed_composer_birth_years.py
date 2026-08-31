"""작곡가 출생년도/시대 보정을 시드한다(시대 분포·다양성 차트용).

출생년도는 CD_LIST 아카이브에서 추출한 표준 표기를 바탕으로 생성된
``apps/time_manage/data/composer_birth_years.json`` 에서 읽는다(작곡가 본인의
생몰년 표기 `성, 이름 (1685-1750)` 에서 파싱). 키는 한글 성(姓)이며, 같은 성을
가진 인물이 여럿이면 아카이브에서 가장 많이 기록된(=합창단이 가장 많이 트는)
인물의 출생년도를 채택한다.

매칭은 백엔드 Composer.name 을 토큰으로 나눠 성(姓)을 **정확히** 대조한다
("요한 제바스티안 바흐"→"바흐", "바흐"→"바흐"). 부분 문자열 매칭은 "라"·"르"
같은 짧은 성 키가 무관한 이름까지 오염시키므로 쓰지 않는다. 이미 birth_year 가
채워진 작곡가는 --force 없이는 건드리지 않는다.

데이터 파일을 새로 만들려면 아카이브(엑셀) 원본에서 재생성한다. 손으로 고치지 말 것.

용례:
    python manage.py seed_composer_birth_years
    python manage.py seed_composer_birth_years --force
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.time_manage.models import Composer

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "composer_birth_years.json"


class Command(BaseCommand):
    help = "아카이브에서 추출한 작곡가 출생년도/시대 보정을 시드한다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="이미 birth_year 가 있는 작곡가도 덮어쓴다.",
        )

    def handle(self, *args, **options):
        force = options["force"]

        if not DATA_FILE.exists():
            raise CommandError(f"데이터 파일을 찾을 수 없습니다: {DATA_FILE}")
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        birth_years = payload.get("birth_years", {})
        era_overrides = payload.get("era_overrides", {})

        updated = 0
        matched_names = set()

        for composer in Composer.objects.all():
            key = self._match_key(composer.name, birth_years)
            if key is None:
                continue
            year = birth_years[key]
            override = era_overrides.get(key)

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
                f"작곡가 {updated}건 업데이트(고유 {len(matched_names)}명). "
                f"전체 {total}명 중 {seeded}명 출생년도 보유. "
                f"(출처 키 {len(birth_years)}개)"
            )
        )

    @staticmethod
    def _match_key(name, birth_years):
        """백엔드 작곡가명 → birth_years 의 키(성). 정확 일치만 허용.

        후보 순서: 이름 전체 → 마지막 토큰(표시 순서의 성) → 첫 토큰.
        """
        name = (name or "").strip()
        if not name:
            return None
        tokens = name.split()
        for cand in (name, tokens[-1], tokens[0]):
            if cand in birth_years:
                return cand
        return None
