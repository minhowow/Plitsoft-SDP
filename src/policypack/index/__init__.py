"""저장소 색인 — 파일 역할과 import 관계.

판정이 파일 하나 안에서 끝나면 다른 파일의 고지·가드·나이 입력을 보지 못한다(중간 평가에서 놓친 양성 21건 가운데
15건). 이 색인은 "이 파일과 함께 봐야 할 파일"을 고른다. 판정은 하지 않는다. `--judge none` 의 판정에는 쓰이지 않는다.

엔진 없이 정규식으로 import 를 읽는다. 놓치는 것(동적 경로, 재수출 체인의 별칭)이 있으므로 색인은 후보를 넓히는
데만 쓰고, 색인에 없다는 것을 근거로 무엇을 지우지 않는다.
"""

from policypack.index.graph import RepoIndex, build_index
from policypack.index.roles import Role, classify

__all__ = ["RepoIndex", "Role", "build_index", "classify"]
