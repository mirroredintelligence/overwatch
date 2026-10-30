// Checks on what the browser may send to the criteria BFF routes (W30, W31). Each refusal is a 400
// with a fixed code and no copy of the value sent. Pure apart from reading the request.
import { badRequest, recordOf } from '@/lib/registration/request';
import type { ChangeInput } from './backend';
import { ageError, districtShape, isNeedCode, REASON_MAX_LENGTH, REVIEW_PERIODS } from './model';
import type { NeedCode, ReviewPeriod } from './types';

const DISTRICT_LIMIT = 20;

function needsOf(value: unknown): NeedCode[] {
  if (!Array.isArray(value) || !value.every(isNeedCode)) badRequest();
  return value as NeedCode[];
}

function wholeOf(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) badRequest();
  return value as number;
}

export function reviewPeriodOf(value: unknown): ReviewPeriod {
  if (typeof value !== 'number' || !(REVIEW_PERIODS as readonly number[]).includes(value)) badRequest();
  return value as ReviewPeriod;
}

/** A change to the criteria: the four values, the reason and the review period. */
export function changeBody(value: unknown): ChangeInput {
  const body = recordOf(value);
  const accepts = needsOf(body.accepts);
  const excludes = needsOf(body.excludes);
  const ageMin = wholeOf(body.ageMin);
  const ageMax = body.ageMax === null || body.ageMax === undefined ? null : wholeOf(body.ageMax);
  if (ageError(ageMin, ageMax) !== null) badRequest();
  if (!Array.isArray(body.districts) || body.districts.length > DISTRICT_LIMIT) badRequest();
  const districts = body.districts.map((district) => {
    if (typeof district !== 'string' || !districtShape(district)) badRequest();
    return district as string;
  });
  if (accepts.some((need) => excludes.includes(need))) badRequest();
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason === '' || reason.length > REASON_MAX_LENGTH) badRequest();
  return { accepts, excludes, ageMin, ageMax, districts, reason, reviewInMonths: reviewPeriodOf(body.reviewInMonths) };
}

/** The review period alone: the confirmation of the current version. */
export function confirmBody(value: unknown): ReviewPeriod {
  return reviewPeriodOf(recordOf(value).reviewInMonths);
}
