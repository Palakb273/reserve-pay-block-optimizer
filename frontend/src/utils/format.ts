export const formatMoney = (paise: number) => new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(paise / 100)

export const formatProbability = (value: string) => `${(Number(value) * 100).toFixed(1)}%`

export const titleCase = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
