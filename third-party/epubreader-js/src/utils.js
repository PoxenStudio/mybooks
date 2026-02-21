const d = (obj, prop) => obj ? obj[prop] : undefined

const q = (src, dst, ext, prop) => {
    let val
    if (typeof dst[prop] === "boolean") {
        switch (prop) {
            case "annotations":
            case "bookmarks":
                val = dst[prop] ? src[prop] : dst[prop]
                break;
            default:
                val = dst[prop]
                break;
        }
    } else if (prop === "arrows") {
        val = dst[prop]
    } else {
        val = d(ext, prop) === undefined ? src[prop] : dst[prop]
    }
    return val
}

export const extend = (src, dst, ext) => {
    for (let prop in src) {
        if (prop === "bookPath") {
            continue
        } else if (dst[prop] instanceof Array) {
            dst[prop] = ext ? (src[prop] ? src[prop] : dst[prop]) : src[prop]
        } else if (dst[prop] instanceof Object) {
            extend(src[prop], dst[prop], d(ext, prop)) // recursive call
        } else {
            dst[prop] = ext ? q(src, dst, ext, prop) : src[prop]
        }
    }
}

export const uuid = () => {
    let d = new Date().getTime()
    const uuid = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        let r = (d + Math.random() * 16) % 16 | 0
        d = Math.floor(d / 16)
        return (c === "x" ? r : (r & 0x7 | 0x8)).toString(16)
    })
    return uuid
}

export const detectMobile = () => {
    const matches = [
        /Android/i,
        /BlackBerry/i,
        /iPhone/i,
        /iPad/i,
        /iPod/i,
        /Windows Phone/i,
        /webOS/i
    ]
    return matches.some((i) => navigator.userAgent.match(i))
}