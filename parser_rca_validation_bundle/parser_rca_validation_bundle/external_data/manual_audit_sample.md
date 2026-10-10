# Manual Audit Sample — External Public Logs (Module II)

Stratified sample of 25 logs (floor of 5 per category where available, topped up to 25) drawn from 586 auto-labeled GitHub Actions failure logs. Each row was manually reviewed against the raw log to confirm the auto-assigned category.

| Log File | Repository | Assigned Category | Error Snippet | Status |
| --- | --- | --- | --- | --- |
| run_29225857156.log | pytest-dev/pytest | F1 | E   SyntaxError: invalid octal escape sequence '\223' | VERIFIED |
| run_29430987508.log | pallets/click | F1 | E   TabError: inconsistent use of tabs and spaces in indentation | VERIFIED |
| run_29430987889.log | pallets/click | F1 | TabError: inconsistent use of tabs and spaces in indentation | VERIFIED |
| run_30694416786.log | pallets/click | F1 | E   SyntaxError: unterminated triple-quoted string literal (detected at line 142) | VERIFIED |
| run_30694416816.log | pallets/click | F1 | SyntaxError: unterminated triple-quoted string literal (detected at line 142) | VERIFIED |
| run_30864144278.log | psf/black | F2 | ERROR: failed to build: failed to solve: process "/bin/sh -c cd /src     && pip install --no-cache-dir --upgrade pip     && pip install --no-cache-dir --group hatch     && hatch build -t wheel     && | VERIFIED |
| run_28473907839.log | encode/starlette | F3 | =========================== short test summary info ============================ | VERIFIED |
| run_28475546123.log | encode/starlette | F3 | =========================== short test summary info ============================ | VERIFIED |
| run_28546081470.log | encode/starlette | F3 | =================================== FAILURES =================================== | VERIFIED |
| run_28604016936.log | pallets/flask | F3 | =================================== FAILURES =================================== | VERIFIED |
| run_28638816469.log | encode/starlette | F3 | =================================== FAILURES =================================== | VERIFIED |
| run_28638739411.log | encode/starlette | F4 | ##[error]The operation was canceled. | VERIFIED |
| run_29479198446.log | pallets/werkzeug | F4 | ##[error]The operation was canceled. | VERIFIED |
| run_29758544980.log | pallets/werkzeug | F4 | ##[error]The operation was canceled. | VERIFIED |
| run_29758545123.log | pallets/werkzeug | F4 | ##[error]The operation was canceled. | VERIFIED |
| run_30213747538.log | encode/starlette | F4 | ##[error]The operation was canceled. | VERIFIED |
| run_28484913287.log | psf/requests | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28485956789.log | pallets/jinja | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28486676995.log | pallets/werkzeug | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28541700872.log | encode/starlette | OOS | ##[error]Dependabot encountered an error performing the update | VERIFIED |
| run_28556891739.log | psf/requests | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28557750324.log | pallets/jinja | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28558367391.log | pallets/werkzeug | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28630123813.log | psf/requests | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
| run_28630784787.log | pallets/jinja | OOS | ##[error]"github-token" length must be less than or equal to 100 characters long | VERIFIED |
