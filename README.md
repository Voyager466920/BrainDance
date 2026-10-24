# BrainDance

ARIS 연구 계획을 탐색하고 기록하는 로컬 연구 워크스페이스입니다. 프로젝트별 가설 트리와 Council 평가, 실제 요청·응답 기록을 함께 확인할 수 있습니다.

## 기능

- 프로젝트 생성·접기·펼치기, 삭제·휴지통 복원
- 한국어 연구 문제·질문·가설과 논문 근거, 아이디어·실험 설계·결과 기록
- Claude 전문가 3명과 독립 Codex 참여자의 제안·익명 교차 평가, Claude Chairman 종합
- 로컬·SSH 장치 조회와 프로젝트별 CPU/GPU 선택, 동시 실행·시간 예산 저장
- GPT(Codex)·Claude 인증 및 계정 한도 사용률 표시. 조회할 수 없는 값은 명시적으로 표시
- 어두운 바탕과 절제된 노랑·청록 포인트

**현재 범위는 연구 계획·기록과 실행 환경 설정입니다. 실험 자동 실행기, GPU 독점 예약, autoresearch는 포함하지 않습니다.**

## 로컬 실행

Python 3.9 이상과 최신 브라우저가 필요합니다. Viewer 자체는 Python 표준 라이브러리만 사용합니다.

```sh
git clone https://github.com/Voyager466920/BrainDance.git
cd BrainDance
python3 .claude/skills/aris-research-council/scripts/viewer.py \
  --db .aris/council/tree.sqlite3 --port 8766
```

브라우저에서 <http://127.0.0.1:8766/>을 엽니다. 첫 실행은 빈 프로젝트 목록으로 시작합니다. `＋ 새 프로젝트`에서 연구 목표와 실행 환경을 선택하세요.

SSH는 기존 SSH config·키·agent를 사용합니다. 원격 장치 조회에는 서버의 `python3`가 필요하며 NVIDIA GPU 조회에는 `nvidia-smi`가 필요합니다. 호스트 키를 자동 수락하지 않습니다. 선택한 장치는 실행 환경 설정이며 GPU 독점 예약이 아닙니다.

## 실제 Research Council 실행

공식 [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep), 로그인된 Claude Code와 Codex CLI가 별도로 필요합니다. ARIS의 논문 탐색 결과를 입력으로 사용하며 공식 `codex-exec` MCP 브리지를 재사용합니다. 프로젝트 로컬 Skill은 [.claude/skills/aris-research-council/SKILL.md](.claude/skills/aris-research-council/SKILL.md)에 있습니다.

자세한 호출 방법과 모드·예산·복구 동작은 [프로토콜](.claude/skills/aris-research-council/references/protocol.md), 토큰 최적화는 [최적화 문서](.claude/skills/aris-research-council/references/optimization.md), 재사용 범위와 라이선스 고지는 [출처](.claude/skills/aris-research-council/references/provenance.md)를 참고하세요. Council 실행에는 연결된 계정의 사용량이 발생합니다.

## 데이터와 계정

연구 DB·입력·결과·실행 로그·계정 정보·SSH 설정은 저장소에 포함하지 않습니다. `.aris/`와 `council/` 등 런타임 디렉터리는 Git에서 제외됩니다. 기존 개인 데이터를 공개 저장소에 추가하지 마세요.

Viewer는 loopback에만 바인딩하며 Host·Origin·CSRF를 확인합니다. 공용 서버로 노출하지 마세요. 계정 사용률 조회는 기존 CLI 인증을 사용하고, macOS Claude 구독 사용량은 Keychain의 기존 OAuth 인증으로 조회합니다. 토큰·계정 식별자를 웹 화면이나 로그에 반환하지 않습니다. 인증됨 표시만으로 추론 실행 권한을 보장하지 않습니다.

## 테스트

```sh
python3 -m unittest discover \
  -s .claude/skills/aris-research-council/scripts -p 'test_*.py'
```

테스트는 임시 DB·loopback HTTP와 합성 입력을 사용합니다. 실제 연구 데이터, 모델 호출이나 GPU 실험은 필요하지 않습니다. JavaScript 렌더링 검증에는 Node.js가 있으면 사용합니다.

## 라이선스

MIT. 재사용한 LLM Council 구성의 고지는 출처 문서에 보존되어 있습니다. 공식 ARIS와 Claude·Codex CLI는 각 프로젝트의 별도 코드·서비스입니다.
