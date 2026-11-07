"""Run gate commits from two threads released together (each commit opens its own connection)."""
import threading


def race(*calls):
    barrier = threading.Barrier(len(calls))
    out = [None] * len(calls)

    def run(i, fn):
        barrier.wait()
        try:
            out[i] = fn()
        except BaseException as e:  # a raise from commit is itself a failure; surface it
            out[i] = e

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "commit hung"
    for o in out:
        assert not isinstance(o, BaseException), repr(o)
    return out


def reset_round(kit):
    kit.sql("DELETE FROM commits")
    kit.sql("DELETE FROM review_tokens")
    kit.tool.calls.clear()
    kit.executes = 0
