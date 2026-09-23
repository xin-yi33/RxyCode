/** Even = collapsed / off. Odd = expanded / on. Starts at 0. */

export class ToggleCounter {
  private value = 0;

  get count(): number {
    return this.value;
  }

  get expanded(): boolean {
    return this.value % 2 === 1;
  }

  increment(): number {
    this.value += 1;
    return this.value;
  }

  reset(): void {
    this.value = 0;
  }
}
