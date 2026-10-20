I maintain code that loops over an `OrderedBidict` and sometimes changes it inside the loop. I want that to fail loudly, the way it does for `dict` and `OrderedDict`, instead of looping forever or silently giving a wrong answer.

The behaviour I want:

- The error is `RuntimeError`, raised from the iteration itself (the next step of the loop), not from the mutating call. The message text doesn't matter.
- It applies to iterating forwards and to iterating with `reversed()`.
- Any change to the structure of the ordered bidict counts: adding a new item, deleting an item, `clear()`, `move_to_end()` (it reorders the items without changing how many there are), and an overwrite that collapses two items into one with `forceput`, so the size can shrink or even stay the same. A check based only on comparing the length before and after would miss these.
- A mutation made through the inverse counts as well: if I iterate `ob` and add an item via `ob.inv`, the loop over `ob` must raise, because they share the same underlying ordering.
- A mutation made while visiting the last item also raises. `OrderedDict` doesn't raise there, but `dict` and the plain `bidict` do, and I don't want code that only breaks on some runs depending on which iteration the mutating branch happens to hit.
- Changing the value of a key that is already present (`ob[key] = new_value` for an existing key) is allowed during iteration and must not raise: it changes no ordering, and the loop should carry on and see the updated values.
- An iterator that was created but not yet advanced also raises if the bidict is mutated before its first step, as `OrderedDict` does: `it = iter(ob); ob[3] = 'three'; list(it)` raises.
- Only the bidict being iterated (and its inverse) is affected. Mutating some other, unrelated `OrderedBidict` during the loop is fine.
- Iteration that is not interrupted by a mutation must behave exactly as before.
