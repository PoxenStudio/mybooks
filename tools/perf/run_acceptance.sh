#!/usr/bin/env bash
# 验收一键脚本：按固定顺序执行 冷启动基线 → 写入类基线 → 下载配额(可选) → 满载压测 → 5s 超时压测。
# 部署：把 run_acceptance.sh、load_probe.py、baseline_probe.py（以及 epub 样本）拷到目标设备的同一个目录，
#       在该目录下执行；所有读写都以当前目录为准，结果写到 ./perf_results/<阶段名>/。
# 用法:
#   export BASE=http://192.168.1.227:8082 USER_NAME=admin MYBOOKS_PASSWORD='******'
#   export EPUB=./2M.epub                          # 可选：带封面的真实 epub，用于上传测试
#   ./run_acceptance.sh                    # 最简：不带参数，结果在 ./perf_results/run-<时间戳>/
#   ./run_acceptance.sh before             # 可选：给本次起个名字（如改造前），结果在 ./perf_results/before/
#   ./run_acceptance.sh phase1a before     # 可选：改造后，并与名为 before 的结果对比 p50
# 可选环境变量: BOOK_ID(下载/详情用的已有书 id，不设则自动挑选) THUMB_BASE(缩略图场景书 id 起点) PLAIN_USER+PLAIN_PASSWORD(普通用户，检查下载配额)
#               REPEAT(默认5) DURATION(默认60) ROUNDS(默认3) PYTHON(默认 python3) SKIP_RESTART_PROMPT=1
set -uo pipefail

PHASE="${1:-run-$(date +%Y%m%d-%H%M%S)}"
COMPARE="${2:-}"
: "${BASE:?请先 export BASE}" "${USER_NAME:?请先 export USER_NAME}" "${MYBOOKS_PASSWORD:?请先 export MYBOOKS_PASSWORD}"
PY="${PYTHON:-python3}"
REPEAT="${REPEAT:-5}"
DURATION="${DURATION:-60}"
ROUNDS="${ROUNDS:-3}"

for f in load_probe.py baseline_probe.py; do
    [ -f "./$f" ] || { echo "当前目录找不到 $f：请把脚本都放在同一目录并在该目录执行（当前目录：$(pwd)）"; exit 2; }
done
OUT="./perf_results/$PHASE"
if [ -n "$COMPARE" ] && [ "$PHASE" = "$COMPARE" ]; then
    echo "阶段名与对比阶段相同（$PHASE），对比基准会被本次结果覆盖，请换一个阶段名"; exit 2
fi
if ls "$OUT"/*.log "$OUT"/*.json >/dev/null 2>&1; then
    STAMP="$(date +%Y%m%d-%H%M%S)"
    mv "$OUT" "$OUT.old-$STAMP"
    [ -f "./perf_results/$PHASE.tar.gz" ] && mv "./perf_results/$PHASE.tar.gz" "./perf_results/$PHASE.old-$STAMP.tar.gz"
    echo "-- 阶段 $PHASE 已有结果，已归档为 $OUT.old-$STAMP（不覆盖、不删除）"
fi
mkdir -p "$OUT"

EPUB_ARGS=()
[ -n "${EPUB:-}" ] && EPUB_ARGS=(--epub "$EPUB")
BOOK_ARGS=()
[ -n "${BOOK_ID:-}" ] && BOOK_ARGS=(--book "$BOOK_ID")
THUMB_ARGS=()
[ -n "${THUMB_BASE:-}" ] && THUMB_ARGS=(--thumb-base "$THUMB_BASE")
CMP_COLD=()
CMP_WRITE=()
if [ -n "$COMPARE" ]; then
    [ -f "perf_results/$COMPARE/baseline_cold.json" ] && CMP_COLD=(--compare "perf_results/$COMPARE/baseline_cold.json")
    [ -f "perf_results/$COMPARE/baseline_write.json" ] && CMP_WRITE=(--compare "perf_results/$COMPARE/baseline_write.json")
fi

FAILED=()
step() {
    local name="$1"; shift
    echo
    echo "################ $name ################"
    "$@" 2>&1 | tee "$OUT/$name.log"
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ]; then
        echo "!! 步骤 $name 退出码 $rc"
        FAILED+=("$name")
    fi
}

echo "阶段=$PHASE 对比=${COMPARE:-无} 目标=$BASE 输出=$OUT"
echo "记录：服务端 commit / 书籍总数 / PERFORMANCE_MODE 请手工写入 $OUT/NOTES.txt"

if [ "${SKIP_RESTART_PROMPT:-0}" != "1" ]; then
    echo
    echo ">>> 请现在重启服务器上的 mybooks（冷启动基线需要刚重启的状态），启动完成后按回车继续"
    read -r _
fi

step 1_baseline_cold "$PY" baseline_probe.py --base "$BASE" --username "$USER_NAME" \
    --repeat "$REPEAT" --json-out "$OUT/baseline_cold.json" ${CMP_COLD[@]+"${CMP_COLD[@]}"}

step 2_baseline_write "$PY" baseline_probe.py --base "$BASE" --username "$USER_NAME" \
    --repeat "$REPEAT" --with-upload --delete-with-data --test-clear-messages \
    ${EPUB_ARGS[@]+"${EPUB_ARGS[@]}"} --json-out "$OUT/baseline_write.json" ${CMP_WRITE[@]+"${CMP_WRITE[@]}"}

if [ -n "${PLAIN_USER:-}" ] && [ -n "${PLAIN_PASSWORD:-}" ]; then
    MYBOOKS_PASSWORD="$PLAIN_PASSWORD" step 3_quota_plain_user "$PY" baseline_probe.py \
        --base "$BASE" --username "$PLAIN_USER" --repeat 4 ${BOOK_ARGS[@]+"${BOOK_ARGS[@]}"}
else
    echo
    echo "-- 跳过步骤 3（未设置 PLAIN_USER/PLAIN_PASSWORD，下载配额无法用管理员账号检测）"
fi

step 4_load "$PY" load_probe.py --base "$BASE" --username "$USER_NAME" \
    --scenario search,search10k,index,thumb,download,upload --delete-with-data \
    ${EPUB_ARGS[@]+"${EPUB_ARGS[@]}"} ${BOOK_ARGS[@]+"${BOOK_ARGS[@]}"} ${THUMB_ARGS[@]+"${THUMB_ARGS[@]}"} \
    --duration "$DURATION" --rounds "$ROUNDS" --quiet

step 5_load_timeout5 "$PY" load_probe.py --base "$BASE" --username "$USER_NAME" \
    --scenario search,index,thumb ${THUMB_ARGS[@]+"${THUMB_ARGS[@]}"} \
    --duration "$DURATION" --rounds 1 --quiet --timeout 5

echo
echo "################ 摘要 ################"
grep -h "配额检查\|^\[.*探针 /api/user/info\|服务端进程 CPU" "$OUT"/*.log 2>/dev/null | cut -c1-200
echo
echo "输出文件："; ls -1 "$OUT"
tar czf "./perf_results/$PHASE.tar.gz" -C ./perf_results "$PHASE" && echo "已打包：./perf_results/$PHASE.tar.gz（需要拷回开发机的就是这一个文件）"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "!! 失败步骤：${FAILED[*]}"
    exit 1
fi
echo "本次结果名：$PHASE；以后要与它对比可执行：./run_acceptance.sh <新名字> $PHASE"
echo "全部步骤完成。下一步：核对设计文档 §4.3 验收判据表，并把 commit/库规模/模式写入 $OUT/NOTES.txt"
