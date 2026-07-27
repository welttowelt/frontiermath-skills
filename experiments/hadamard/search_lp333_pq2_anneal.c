#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { LENGTH = 333, HALF = 166, ROWS = 2, CLASSES = 3 };

typedef struct {
  uint64_t state;
} rng_t;

typedef struct {
  int8_t values[ROWS][LENGTH];
  int paf[ROWS][HALF + 1];
  int residual[HALF + 1];
  long long objective;
} state_t;

typedef struct {
  uint64_t iterations;
  uint64_t accepted;
  uint64_t improving;
  uint64_t restarts;
  long long best_objective;
  int best_max_abs_residual;
  state_t best;
} search_record_t;

static const int negative_targets[ROWS][CLASSES] = {
    {55, 50, 61},
    {55, 61, 50},
};

static uint64_t rng_next(rng_t *rng) {
  uint64_t x = rng->state;
  x ^= x >> 12;
  x ^= x << 25;
  x ^= x >> 27;
  rng->state = x;
  return x * UINT64_C(2685821657736338717);
}

static double monotonic_seconds(void) {
  struct timespec value;
  if (clock_gettime(CLOCK_MONOTONIC, &value)) {
    perror("clock_gettime");
    exit(2);
  }
  return (double)value.tv_sec + 1e-9 * (double)value.tv_nsec;
}

static int wrapped(int index) {
  index %= LENGTH;
  return index < 0 ? index + LENGTH : index;
}

static void initialize_row(int8_t row[LENGTH], int row_index, rng_t *rng) {
  for (int index = 0; index < LENGTH; ++index)
    row[index] = 1;
  for (int residue = 0; residue < CLASSES; ++residue) {
    int positions[111];
    for (int item = 0; item < 111; ++item)
      positions[item] = residue + 3 * item;
    for (int item = 110; item > 0; --item) {
      int other = (int)(rng_next(rng) % (uint64_t)(item + 1));
      int temporary = positions[item];
      positions[item] = positions[other];
      positions[other] = temporary;
    }
    for (int item = 0; item < negative_targets[row_index][residue]; ++item)
      row[positions[item]] = -1;
  }
}

static void compute_paf(const int8_t row[LENGTH], int paf[HALF + 1]) {
  paf[0] = LENGTH;
  for (int shift = 1; shift <= HALF; ++shift) {
    int total = 0;
    for (int index = 0; index < LENGTH; ++index)
      total += row[index] * row[wrapped(index + shift)];
    paf[shift] = total;
  }
}

static long long refresh_objective(state_t *state) {
  compute_paf(state->values[0], state->paf[0]);
  compute_paf(state->values[1], state->paf[1]);
  long long objective = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int residual = state->paf[0][shift] + state->paf[1][shift] + 2;
    state->residual[shift] = residual;
    objective += (long long)residual * residual;
  }
  state->objective = objective;
  return objective;
}

static void initialize_state(state_t *state, rng_t *rng) {
  initialize_row(state->values[0], 0, rng);
  initialize_row(state->values[1], 1, rng);
  refresh_objective(state);
}

static int max_abs_residual(const state_t *state) {
  int result = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int value = state->residual[shift];
    if (value < 0)
      value = -value;
    if (value > result)
      result = value;
  }
  return result;
}

static long long l1_residual(const state_t *state) {
  long long result = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int value = state->residual[shift];
    result += value < 0 ? -value : value;
  }
  return result;
}

static void choose_swap(const state_t *state, int row, rng_t *rng, int *left,
                        int *right) {
  int residue = (int)(rng_next(rng) % CLASSES);
  int first = residue + 3 * (int)(rng_next(rng) % 111);
  int second;
  do {
    second = residue + 3 * (int)(rng_next(rng) % 111);
  } while (state->values[row][first] == state->values[row][second]);
  *left = first;
  *right = second;
}

static int value_after_flip(const int8_t row[LENGTH], int index, int left,
                            int right) {
  int value = row[index];
  return index == left || index == right ? -value : value;
}

static void swap_paf_delta(const int8_t row[LENGTH], int left, int right,
                           int delta[HALF + 1]) {
  delta[0] = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    int starts[4] = {left, right, wrapped(left - shift),
                     wrapped(right - shift)};
    int change = 0;
    for (int item = 0; item < 4; ++item) {
      int start = starts[item];
      int duplicate = 0;
      for (int prior = 0; prior < item; ++prior)
        if (starts[prior] == start)
          duplicate = 1;
      if (duplicate)
        continue;
      int end = wrapped(start + shift);
      int old_product = row[start] * row[end];
      int new_product = value_after_flip(row, start, left, right) *
                        value_after_flip(row, end, left, right);
      change += new_product - old_product;
    }
    delta[shift] = change;
  }
}

static long long objective_after_delta(const state_t *state,
                                       const int delta[HALF + 1]) {
  long long result = 0;
  for (int shift = 1; shift <= HALF; ++shift) {
    long long value = state->residual[shift] + delta[shift];
    result += value * value;
  }
  return result;
}

static void apply_swap(state_t *state, int row, int left, int right,
                       const int delta[HALF + 1], long long objective) {
  state->values[row][left] = -state->values[row][left];
  state->values[row][right] = -state->values[row][right];
  for (int shift = 1; shift <= HALF; ++shift) {
    state->paf[row][shift] += delta[shift];
    state->residual[shift] += delta[shift];
  }
  state->objective = objective;
}

static int exact_margins_hold(const state_t *state) {
  for (int row = 0; row < ROWS; ++row)
    for (int residue = 0; residue < CLASSES; ++residue) {
      int negatives = 0;
      for (int index = residue; index < LENGTH; index += CLASSES)
        negatives += state->values[row][index] == -1;
      if (negatives != negative_targets[row][residue])
        return 0;
    }
  return 1;
}

static int incremental_self_test(void) {
  rng_t rng = {UINT64_C(0x6a09e667f3bcc909)};
  state_t state;
  initialize_state(&state, &rng);
  for (int trial = 0; trial < 2000; ++trial) {
    int row = (int)(rng_next(&rng) % ROWS);
    int left, right;
    int delta[HALF + 1];
    choose_swap(&state, row, &rng, &left, &right);
    swap_paf_delta(state.values[row], left, right, delta);
    long long predicted = objective_after_delta(&state, delta);
    state_t direct = state;
    direct.values[row][left] = -direct.values[row][left];
    direct.values[row][right] = -direct.values[row][right];
    long long actual = refresh_objective(&direct);
    if (predicted != actual)
      return 0;
    for (int shift = 1; shift <= HALF; ++shift)
      if (state.paf[row][shift] + delta[shift] != direct.paf[row][shift])
        return 0;
    apply_swap(&state, row, left, right, delta, predicted);
    if (!exact_margins_hold(&state))
      return 0;
  }
  state_t refreshed = state;
  if (refresh_objective(&refreshed) != state.objective)
    return 0;
  return !memcmp(refreshed.residual, state.residual, sizeof(state.residual));
}

static void emit_progress(const search_record_t *record, double elapsed,
                          uint64_t seed) {
  printf("{\"elapsed_seconds\":%.1f,\"seed\":%llu,"
         "\"iterations\":%llu,\"accepted\":%llu,\"restarts\":%llu,"
         "\"best_objective\":%lld,\"best_l1\":%lld,"
         "\"best_max_abs_residual\":%d}\n",
         elapsed, (unsigned long long)seed,
         (unsigned long long)record->iterations,
         (unsigned long long)record->accepted,
         (unsigned long long)record->restarts, record->best_objective,
         l1_residual(&record->best), record->best_max_abs_residual);
  fflush(stdout);
}

static void write_array(FILE *output, const int8_t values[LENGTH]) {
  fputc('[', output);
  for (int index = 0; index < LENGTH; ++index) {
    if (index)
      fputc(',', output);
    fprintf(output, "%d", values[index]);
  }
  fputc(']', output);
}

static void write_int_array(FILE *output, const int values[HALF + 1]) {
  fputc('[', output);
  for (int shift = 1; shift <= HALF; ++shift) {
    if (shift > 1)
      fputc(',', output);
    fprintf(output, "%d", values[shift]);
  }
  fputc(']', output);
}

static void write_result(const char *path, const search_record_t *record,
                         uint64_t seed, double elapsed, double max_seconds,
                         uint64_t moves_per_restart) {
  FILE *output = fopen(path, "w");
  if (!output) {
    fprintf(stderr, "failed to open '%s': %s\n", path, strerror(errno));
    exit(2);
  }
  fprintf(output,
          "{\n"
          "  \"schema\": \"frontiermath-lp333-pq2-anneal-result-v1\",\n"
          "  \"status\": \"%s\",\n"
          "  \"seed\": %llu,\n"
          "  \"elapsed_seconds\": %.9f,\n"
          "  \"max_seconds\": %.9f,\n"
          "  \"moves_per_restart\": %llu,\n"
          "  \"iterations\": %llu,\n"
          "  \"accepted\": %llu,\n"
          "  \"improving\": %llu,\n"
          "  \"restarts\": %llu,\n"
          "  \"incremental_self_test_trials\": 2000,\n"
          "  \"incremental_self_test\": \"PASS\",\n"
          "  \"best_objective\": %lld,\n"
          "  \"best_l1_residual\": %lld,\n"
          "  \"best_max_abs_residual\": %d,\n"
          "  \"a_sequence\": ",
          record->best_objective == 0 ? "candidate" : "nonterminal",
          (unsigned long long)seed, elapsed, max_seconds,
          (unsigned long long)moves_per_restart,
          (unsigned long long)record->iterations,
          (unsigned long long)record->accepted,
          (unsigned long long)record->improving,
          (unsigned long long)record->restarts, record->best_objective,
          l1_residual(&record->best), record->best_max_abs_residual);
  write_array(output, record->best.values[0]);
  fprintf(output, ",\n  \"b_sequence\": ");
  write_array(output, record->best.values[1]);
  fprintf(output, ",\n  \"a_paf_independent\": ");
  write_int_array(output, record->best.paf[0]);
  fprintf(output, ",\n  \"b_paf_independent\": ");
  write_int_array(output, record->best.paf[1]);
  fprintf(output, ",\n  \"combined_residual_independent\": ");
  write_int_array(output, record->best.residual);
  fprintf(output, "\n}\n");
  if (fclose(output)) {
    perror("fclose");
    exit(2);
  }
}

static int run_search(double max_seconds, uint64_t seed, const char *output_path,
                      uint64_t moves_per_restart) {
  if (!incremental_self_test()) {
    fprintf(stderr, "incremental self-test failed\n");
    return 2;
  }
  rng_t rng = {seed ? seed : UINT64_C(0x9e3779b97f4a7c15)};
  state_t current;
  initialize_state(&current, &rng);
  search_record_t record;
  memset(&record, 0, sizeof(record));
  record.best = current;
  record.best_objective = current.objective;
  record.best_max_abs_residual = max_abs_residual(&current);

  const double started = monotonic_seconds();
  double next_progress = 60.0;
  uint64_t move_in_restart = 0;
  double temperature = 512.0;
  while (record.best_objective != 0) {
    if (!(record.iterations & UINT64_C(65535))) {
      double elapsed = monotonic_seconds() - started;
      if (elapsed >= max_seconds)
        break;
      if (elapsed >= next_progress) {
        emit_progress(&record, elapsed, seed);
        next_progress += 60.0;
      }
    }
    if (move_in_restart >= moves_per_restart) {
      initialize_state(&current, &rng);
      ++record.restarts;
      move_in_restart = 0;
      temperature = 512.0;
    }
    if (!(move_in_restart & UINT64_C(4095))) {
      double fraction = (double)move_in_restart / (double)moves_per_restart;
      temperature = 512.0 * pow(0.25 / 512.0, fraction);
    }
    int row = (int)(rng_next(&rng) % ROWS);
    int left, right;
    int delta[HALF + 1];
    choose_swap(&current, row, &rng, &left, &right);
    swap_paf_delta(current.values[row], left, right, delta);
    long long proposed = objective_after_delta(&current, delta);
    long long increase = proposed - current.objective;
    int accept = increase <= 0;
    if (!accept) {
      double uniform =
          ((rng_next(&rng) >> 11) + 0.5) * (1.0 / 9007199254740992.0);
      accept = uniform < exp(-(double)increase / temperature);
    }
    ++record.iterations;
    ++move_in_restart;
    if (!accept)
      continue;
    if (proposed < current.objective)
      ++record.improving;
    ++record.accepted;
    apply_swap(&current, row, left, right, delta, proposed);
    if (current.objective < record.best_objective) {
      record.best = current;
      record.best_objective = current.objective;
      record.best_max_abs_residual = max_abs_residual(&current);
    }
  }
  double elapsed = monotonic_seconds() - started;
  if (!exact_margins_hold(&record.best) ||
      refresh_objective(&record.best) != record.best_objective) {
    fprintf(stderr, "final direct refresh or margin check failed\n");
    return 2;
  }
  emit_progress(&record, elapsed, seed);
  write_result(output_path, &record, seed, elapsed, max_seconds,
               moves_per_restart);
  return 0;
}

static void usage(const char *program) {
  fprintf(stderr,
          "usage: %s --self-test | --initial --seed N | "
          "--seconds N --seed N --output PATH "
          "[--moves-per-restart N]\n",
          program);
}

int main(int argc, char **argv) {
  int self_test = 0;
  int initial = 0;
  double seconds = 0;
  uint64_t seed = 0;
  uint64_t moves_per_restart = UINT64_C(2000000);
  const char *output = NULL;
  for (int index = 1; index < argc; ++index) {
    if (!strcmp(argv[index], "--self-test")) {
      self_test = 1;
    } else if (!strcmp(argv[index], "--initial")) {
      initial = 1;
    } else if (!strcmp(argv[index], "--seconds") && index + 1 < argc) {
      seconds = strtod(argv[++index], NULL);
    } else if (!strcmp(argv[index], "--seed") && index + 1 < argc) {
      seed = strtoull(argv[++index], NULL, 10);
    } else if (!strcmp(argv[index], "--output") && index + 1 < argc) {
      output = argv[++index];
    } else if (!strcmp(argv[index], "--moves-per-restart") &&
               index + 1 < argc) {
      moves_per_restart = strtoull(argv[++index], NULL, 10);
    } else {
      usage(argv[0]);
      return 2;
    }
  }
  if (self_test) {
    int pass = incremental_self_test();
    printf("{\"incremental_self_test\":\"%s\",\"trials\":2000}\n",
           pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
  }
  if (initial) {
    if (!seed) {
      usage(argv[0]);
      return 2;
    }
    rng_t rng = {seed};
    state_t state;
    initialize_state(&state, &rng);
    printf("{\"seed\":%llu,\"initial_objective\":%lld,"
           "\"initial_l1\":%lld,\"initial_max_abs_residual\":%d,"
           "\"margins\":\"%s\"}\n",
           (unsigned long long)seed, state.objective, l1_residual(&state),
           max_abs_residual(&state),
           exact_margins_hold(&state) ? "PASS" : "FAIL");
    return exact_margins_hold(&state) ? 0 : 1;
  }
  if (!(seconds > 0) || !seed || !output || !moves_per_restart) {
    usage(argv[0]);
    return 2;
  }
  return run_search(seconds, seed, output, moves_per_restart);
}
