import { Link } from 'react-router-dom'

/** variant: primary (black pill, default) | secondary | ghost | danger | ok. size: sm | md | lg */
export default function Button({ variant = 'primary', size = 'md', block = false, to, href, loading = false, children, className = '', ...rest }) {
  const cls = `btn btn-${variant} ${size !== 'md' ? `btn-${size}` : ''} ${block ? 'btn-block' : ''} ${className}`.trim()
  const content = (
    <>
      {loading && <span className="spinner" style={{ borderTopColor: variant === 'primary' ? '#fff' : undefined }} />}
      {children}
    </>
  )
  if (to) return <Link to={to} className={cls} {...rest}>{content}</Link>
  if (href) return <a href={href} className={cls} {...rest}>{content}</a>
  return (
    <button className={cls} disabled={rest.disabled || loading} {...rest}>
      {content}
    </button>
  )
}
