function myMiddleware(req, res, next)
{
    try {
        //1. Perform some checks
        //2. Add data tto req
        next()
    } catch (error) {
        next(error)
    }
}